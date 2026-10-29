// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Leasing: leases of units to tenants, the rent roll and the arrears board.
 *
 * Rent invoices are raised in finance as drafts; arrears are read back from
 * finance payments, so the page never keeps a second ledger.
 */
import { Fragment, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlarmClock, ArrowRight, Download, FileSignature, KeyRound, Network, Plus, Receipt, Wallet } from 'lucide-react';
import { Badge, Button, Card, CollapsibleSection, EmptyState, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtCurrency, fmtDate } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import {
  createLease,
  downloadExport,
  fetchArrears,
  fetchExportProfiles,
  fetchLeases,
  fetchRentRoll,
  runSchedule,
  type EscalationKind,
  type Frequency,
  type LeaseCreate,
  type LeaseStatus,
  type UnitKind,
} from './api';
import { buildLeasingInsights } from './leasingInsights';
import { bucketLabel, frequencyLabel, statusLabel } from './leasingLabels';

type Tab = 'leases' | 'rent_roll' | 'arrears';

export const STATUS_VARIANT: Record<LeaseStatus, 'neutral' | 'success' | 'warning' | 'blue'> = {
  draft: 'neutral',
  active: 'success',
  notice: 'warning',
  ended: 'blue',
};

function HowItWorks() {
  const { t } = useTranslation();
  const steps = [
    {
      icon: <FileSignature size={14} className="text-oe-blue" />,
      title: t('leasing.flow_1_title', { defaultValue: 'Draft the lease' }),
      desc: t('leasing.flow_1_desc', {
        defaultValue: 'Unit, tenant, landlord, term, rent, deposit and escalation. The checks run on every save.',
      }),
    },
    {
      icon: <KeyRound size={14} className="text-oe-blue" />,
      title: t('leasing.flow_2_title', { defaultValue: 'Activate' }),
      desc: t('leasing.flow_2_desc', {
        defaultValue: 'Activation builds the rent schedule. One unit holds one live lease at a time.',
      }),
    },
    {
      icon: <Receipt size={14} className="text-oe-blue" />,
      title: t('leasing.flow_3_title', { defaultValue: 'Raise rent invoices' }),
      desc: t('leasing.flow_3_desc', {
        defaultValue: 'Due rent becomes draft invoices in finance, which approves and sends them as usual.',
      }),
    },
    {
      icon: <AlarmClock size={14} className="text-oe-blue" />,
      title: t('leasing.flow_4_title', { defaultValue: 'Follow arrears' }),
      desc: t('leasing.flow_4_desc', {
        defaultValue: 'Overdue rent is read from finance payments, by age, per lease and tenant.',
      }),
    },
  ];
  return (
    <CollapsibleSection
      storageKey="leasing.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('leasing.flow_title', { defaultValue: 'How leasing fits together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('leasing.flow_intro', {
          defaultValue:
            'Lease the units you built or manage, bill the rent through finance and see who is behind, without a second ledger.',
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
              <li aria-hidden="true" className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex">
                <ArrowRight size={16} className="rtl:rotate-180" />
              </li>
            )}
          </Fragment>
        ))}
      </ol>
      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">{t('leasing.flow_connects', { defaultValue: 'Connects with:' })}</span>{' '}
        <Link className="text-oe-blue hover:underline" to="/property-dev">
          {t('leasing.mod_property_dev', { defaultValue: 'Property development' })}
        </Link>{' '}
        ·{' '}
        <Link className="text-oe-blue hover:underline" to="/contacts">
          {t('leasing.mod_contacts', { defaultValue: 'Contacts' })}
        </Link>{' '}
        ·{' '}
        <Link className="text-oe-blue hover:underline" to="/finance">
          {t('leasing.mod_finance', { defaultValue: 'Finance' })}
        </Link>{' '}
        ·{' '}
        <Link className="text-oe-blue hover:underline" to="/documents">
          {t('leasing.mod_documents', { defaultValue: 'Documents' })}
        </Link>
      </div>
    </CollapsibleSection>
  );
}

const inputCls =
  'w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

function NewLeaseForm({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [tenantName, setTenantName] = useState('');
  const [form, setForm] = useState<LeaseCreate>({
    project_id: projectId,
    code: '',
    unit_kind: 'plot',
    unit_ref: '',
    unit_label: '',
    tenant_contact_id: '',
    start_date: '',
    end_date: '',
    rent_amount: '',
    currency: '',
    frequency: 'monthly',
    deposit: '0',
    escalation_kind: 'none',
    escalation_rate: null,
    escalation_every_months: 12,
    tax_rate: '0',
    payment_terms_days: 0,
  });
  const set = <K extends keyof LeaseCreate>(k: K, v: LeaseCreate[K]) => setForm((f) => ({ ...f, [k]: v }));
  const mutation = useMutation({
    mutationFn: () => createLease({ ...form, currency: form.currency.toUpperCase() }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('leasing.created', { defaultValue: 'Lease saved as a draft' }) });
      onDone();
    },
    onError: (e) =>
      addToast({ type: 'error', title: t('leasing.save_failed', { defaultValue: 'Could not save the lease' }), message: getErrorMessage(e) }),
  });
  const ready =
    form.code && form.unit_ref && form.tenant_contact_id && form.start_date && form.end_date && form.rent_amount && form.currency.length === 3;
  const field = (label: string, node: ReactNode) => (
    <label className="flex flex-col gap-1 text-xs text-content-secondary">
      <span>{label}</span>
      {node}
    </label>
  );
  return (
    <Card padding="sm" data-testid="leasing-new-form">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {field(t('leasing.col_code', { defaultValue: 'Lease' }), <input className={inputCls} value={form.code} onChange={(e) => set('code', e.target.value)} />)}
        {field(
          t('leasing.f_unit_kind', { defaultValue: 'Unit type' }),
          <select className={inputCls} value={form.unit_kind} onChange={(e) => set('unit_kind', e.target.value as UnitKind)}>
            <option value="plot">{t('leasing.unit_plot', { defaultValue: 'Plot or unit of a development' })}</option>
            <option value="asset">{t('leasing.unit_asset', { defaultValue: 'Asset register entry' })}</option>
            <option value="unit">{t('leasing.unit_other', { defaultValue: 'Other unit' })}</option>
          </select>,
        )}
        {field(t('leasing.f_unit_ref', { defaultValue: 'Unit reference' }), <input className={inputCls} value={form.unit_ref} onChange={(e) => set('unit_ref', e.target.value)} />)}
        {field(t('leasing.col_unit', { defaultValue: 'Unit' }), <input className={inputCls} value={form.unit_label} onChange={(e) => set('unit_label', e.target.value)} />)}
        <div className="sm:col-span-2">
          {field(
            t('leasing.col_tenant', { defaultValue: 'Tenant' }),
            <ContactSearchInput
              value={form.tenant_contact_id}
              displayValue={tenantName}
              onChange={(id, name) => {
                set('tenant_contact_id', id);
                setTenantName(name);
              }}
            />,
          )}
        </div>
        {field(t('leasing.col_start', { defaultValue: 'Start' }), <input type="date" className={inputCls} value={form.start_date} onChange={(e) => set('start_date', e.target.value)} />)}
        {field(t('leasing.col_end', { defaultValue: 'End' }), <input type="date" className={inputCls} value={form.end_date} onChange={(e) => set('end_date', e.target.value)} />)}
        {field(t('leasing.col_rent', { defaultValue: 'Rent per period' }), <input inputMode="decimal" dir="ltr" className={inputCls} value={form.rent_amount} onChange={(e) => set('rent_amount', e.target.value)} />)}
        {field(t('leasing.f_currency', { defaultValue: 'Currency' }), <input maxLength={3} dir="ltr" className={inputCls} value={form.currency} onChange={(e) => set('currency', e.target.value)} />)}
        {field(
          t('leasing.col_frequency', { defaultValue: 'Billed' }),
          <select className={inputCls} value={form.frequency} onChange={(e) => set('frequency', e.target.value as Frequency)}>
            {(['monthly', 'quarterly', 'semiannual', 'annual'] as Frequency[]).map((f) => (
              <option key={f} value={f}>{frequencyLabel(f, t)}</option>
            ))}
          </select>,
        )}
        {field(t('leasing.col_deposit', { defaultValue: 'Deposit' }), <input inputMode="decimal" dir="ltr" className={inputCls} value={form.deposit} onChange={(e) => set('deposit', e.target.value)} />)}
        {field(
          t('leasing.f_escalation', { defaultValue: 'Escalation' }),
          <select className={inputCls} value={form.escalation_kind} onChange={(e) => set('escalation_kind', e.target.value as EscalationKind)}>
            <option value="none">{t('leasing.esc_none', { defaultValue: 'No escalation' })}</option>
            <option value="fixed">{t('leasing.esc_fixed', { defaultValue: 'Fixed percent' })}</option>
            <option value="index">{t('leasing.esc_index', { defaultValue: 'Linked to an index' })}</option>
          </select>,
        )}
        {form.escalation_kind === 'fixed' &&
          field(
            t('leasing.f_escalation_rate', { defaultValue: 'Rise per review, %' }),
            <input inputMode="decimal" dir="ltr" className={inputCls} value={form.escalation_rate ?? ''} onChange={(e) => set('escalation_rate', e.target.value || null)} />,
          )}
        {form.escalation_kind !== 'none' &&
          field(
            t('leasing.f_escalation_every', { defaultValue: 'Review every (months)' }),
            <input type="number" min={1} className={inputCls} value={form.escalation_every_months} onChange={(e) => set('escalation_every_months', Number(e.target.value) || 12)} />,
          )}
        {field(t('leasing.f_tax_rate', { defaultValue: 'Tax rate, %' }), <input inputMode="decimal" dir="ltr" className={inputCls} value={form.tax_rate} onChange={(e) => set('tax_rate', e.target.value)} />)}
        {field(t('leasing.f_terms', { defaultValue: 'Payment terms (days)' }), <input type="number" min={0} className={inputCls} value={form.payment_terms_days} onChange={(e) => set('payment_terms_days', Number(e.target.value) || 0)} />)}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onDone}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button variant="primary" size="sm" disabled={!ready || mutation.isPending} onClick={() => mutation.mutate()} data-testid="leasing-save">
          {t('leasing.save_draft', { defaultValue: 'Save draft' })}
        </Button>
      </div>
    </Card>
  );
}

export function LeasingPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const [tab, setTab] = useState<Tab>('leases');
  const [showNew, setShowNew] = useState(false);

  const leasesQ = useQuery({ queryKey: ['leasing', 'list', projectId], queryFn: () => fetchLeases(projectId), enabled: !!projectId });
  const rollQ = useQuery({ queryKey: ['leasing', 'roll', projectId], queryFn: () => fetchRentRoll(projectId), enabled: !!projectId && tab === 'rent_roll' });
  const arrearsQ = useQuery({ queryKey: ['leasing', 'arrears', projectId], queryFn: () => fetchArrears(projectId), enabled: !!projectId && tab === 'arrears' });
  const profilesQ = useQuery({ queryKey: ['leasing', 'profiles'], queryFn: fetchExportProfiles, staleTime: 3_600_000 });

  const leases = leasesQ.data ?? [];
  const insights = useModuleInsights('leasing', { defaultOpen: false });
  const { datasets, builtins } = useMemo(() => buildLeasingInsights(leases, t), [leases, t]);

  const run = useMutation({
    mutationFn: () => runSchedule(projectId),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('leasing.run_done', { defaultValue: 'Rent invoices raised as drafts in finance: {{n}}', n: r.invoices_created }),
      });
      qc.invalidateQueries({ queryKey: ['leasing'] });
    },
    onError: (e) => addToast({ type: 'error', title: t('leasing.run_failed', { defaultValue: 'Could not raise rent invoices' }), message: getErrorMessage(e) }),
  });

  const tabLabel = (v: Tab) =>
    v === 'leases'
      ? t('leasing.tab_leases', { defaultValue: 'Leases' })
      : v === 'rent_roll'
        ? t('leasing.tab_rent_roll', { defaultValue: 'Rent roll' })
        : t('leasing.tab_arrears', { defaultValue: 'Arrears' });

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('leasing.title', { defaultValue: 'Leasing' })}
        subtitle={t('leasing.subtitle', {
          defaultValue: 'Leases of units to tenants, the rent they owe and who is behind, billed through finance.',
        })}
        actions={
          projectId ? (
            <div className="flex flex-wrap items-center gap-2">
              <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
              {(profilesQ.data ?? []).map((p) => (
                <Button key={p} variant="ghost" size="sm" icon={<Download size={14} />} onClick={() => void downloadExport(projectId, p)}>
                  {t('leasing.export_as', { defaultValue: 'Export {{format}}', format: p.toUpperCase() })}
                </Button>
              ))}
              <Button variant="secondary" size="sm" icon={<Receipt size={14} />} disabled={run.isPending} onClick={() => run.mutate()} data-testid="leasing-run">
                {t('leasing.run', { defaultValue: 'Raise due rent' })}
              </Button>
              <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setShowNew(true)} data-testid="leasing-new">
                {t('leasing.new', { defaultValue: 'New lease' })}
              </Button>
            </div>
          ) : undefined
        }
      />
      <HowItWorks />
      {!projectId ? (
        <RequiresProject>{null}</RequiresProject>
      ) : (
        <>
          {showNew && (
            <NewLeaseForm
              projectId={projectId}
              onDone={() => {
                setShowNew(false);
                qc.invalidateQueries({ queryKey: ['leasing'] });
              }}
            />
          )}
          <div className="inline-flex rounded-lg border border-border bg-surface-secondary p-0.5" role="tablist">
            {(['leases', 'rent_roll', 'arrears'] as Tab[]).map((v) => (
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
                {tabLabel(v)}
              </button>
            ))}
          </div>

          {tab === 'leases' && (
            <>
              <InsightsPanel
                open={insights.open}
                title={t('leasing.insights_title', { defaultValue: 'Leasing insights' })}
                datasets={datasets}
                builtins={builtins}
                custom={insights.custom}
                onAdd={insights.addCustom}
                onUpdate={insights.updateCustom}
                onRemove={insights.removeCustom}
                onCollapse={() => insights.setOpen(false)}
              />
              <Card padding="none" className="overflow-x-auto">
                {leasesQ.isLoading ? (
                  <SkeletonTable rows={4} columns={6} />
                ) : leases.length === 0 ? (
                  <EmptyState
                    icon={<FileSignature size={20} />}
                    title={t('leasing.empty_title', { defaultValue: 'No leases yet' })}
                    description={t('leasing.empty_desc', { defaultValue: 'Draft the first lease of a unit in this project.' })}
                  />
                ) : (
                  <table className="w-full text-sm">
                    <thead className="text-xs text-content-tertiary">
                      <tr className="border-b border-border-light">
                        <th className="px-3 py-2 text-start">{t('leasing.col_code', { defaultValue: 'Lease' })}</th>
                        <th className="px-3 py-2 text-start">{t('leasing.col_unit', { defaultValue: 'Unit' })}</th>
                        <th className="px-3 py-2 text-start">{t('leasing.col_term', { defaultValue: 'Term' })}</th>
                        <th className="px-3 py-2 text-end">{t('leasing.col_rent', { defaultValue: 'Rent per period' })}</th>
                        <th className="px-3 py-2 text-start">{t('leasing.col_frequency', { defaultValue: 'Billed' })}</th>
                        <th className="px-3 py-2 text-start">{t('leasing.col_status', { defaultValue: 'Status' })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {leases.map((l) => (
                        <tr key={l.id} className="border-b border-border-light last:border-0 hover:bg-surface-secondary/50">
                          <td className="px-3 py-2">
                            <Link className="font-medium text-oe-blue hover:underline" to={`/leasing/${l.id}`}>
                              {l.code}
                            </Link>
                          </td>
                          <td className="px-3 py-2">{l.unit_label || l.unit_ref}</td>
                          <td className="px-3 py-2 whitespace-nowrap">
                            {fmtDate(l.start_date)} – {fmtDate(l.end_date)}
                          </td>
                          <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(l.rent_amount, l.currency)}</td>
                          <td className="px-3 py-2">{frequencyLabel(l.frequency, t)}</td>
                          <td className="px-3 py-2">
                            <Badge variant={STATUS_VARIANT[l.status]} size="sm">
                              {statusLabel(l.status, t)}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>
            </>
          )}

          {tab === 'rent_roll' && (
            <Card padding="none" className="overflow-x-auto">
              {rollQ.isLoading ? (
                <SkeletonTable rows={4} columns={6} />
              ) : (rollQ.data?.items ?? []).length === 0 ? (
                <EmptyState
                  icon={<Wallet size={20} />}
                  title={t('leasing.roll_empty', { defaultValue: 'No live leases' })}
                  description={t('leasing.roll_empty_desc', { defaultValue: 'Active leases and leases under notice appear here.' })}
                />
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-xs text-content-tertiary">
                    <tr className="border-b border-border-light">
                      <th className="px-3 py-2 text-start">{t('leasing.col_unit', { defaultValue: 'Unit' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_code', { defaultValue: 'Lease' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_tenant', { defaultValue: 'Tenant' })}</th>
                      <th className="px-3 py-2 text-end">{t('leasing.col_current_rent', { defaultValue: 'Current rent' })}</th>
                      <th className="px-3 py-2 text-end">{t('leasing.col_annual_rent', { defaultValue: 'Annual rent' })}</th>
                      <th className="px-3 py-2 text-end">{t('leasing.col_deposit', { defaultValue: 'Deposit' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_next_due', { defaultValue: 'Next due' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_end', { defaultValue: 'End' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(rollQ.data?.items ?? []).map((r) => (
                      <tr key={r.lease_id} className="border-b border-border-light last:border-0">
                        <td className="px-3 py-2">{r.unit_label || r.unit_ref}</td>
                        <td className="px-3 py-2">
                          <Link className="text-oe-blue hover:underline" to={`/leasing/${r.lease_id}`}>
                            {r.code}
                          </Link>{' '}
                          <Badge variant={STATUS_VARIANT[r.status]} size="sm">
                            {statusLabel(r.status, t)}
                          </Badge>
                        </td>
                        <td className="px-3 py-2">{r.tenant_name}</td>
                        <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(r.current_rent, r.currency)}</td>
                        <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(r.annual_rent, r.currency)}</td>
                        <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(r.deposit, r.currency)}</td>
                        <td className="px-3 py-2">{r.next_due_date ? fmtDate(r.next_due_date) : '–'}</td>
                        <td className="px-3 py-2">{fmtDate(r.end_date)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    {Object.entries(rollQ.data?.totals ?? {}).map(([cur, v]) => (
                      <tr key={cur} className="font-semibold">
                        <td className="px-3 py-2" colSpan={4}>
                          {t('leasing.total', { defaultValue: 'Total' })}
                        </td>
                        <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(v, cur)}</td>
                        <td colSpan={3} />
                      </tr>
                    ))}
                  </tfoot>
                </table>
              )}
            </Card>
          )}

          {tab === 'arrears' && (
            <Card padding="none" className="overflow-x-auto">
              {arrearsQ.isLoading ? (
                <SkeletonTable rows={4} columns={6} />
              ) : (arrearsQ.data?.items ?? []).length === 0 ? (
                <EmptyState
                  icon={<AlarmClock size={20} />}
                  title={t('leasing.arrears_empty', { defaultValue: 'Nobody is behind' })}
                  description={t('leasing.arrears_empty_desc', {
                    defaultValue: 'Overdue rent shows here once finance has sent the invoice and its due date has passed.',
                  })}
                />
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-xs text-content-tertiary">
                    <tr className="border-b border-border-light">
                      <th className="px-3 py-2 text-start">{t('leasing.col_code', { defaultValue: 'Lease' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_unit', { defaultValue: 'Unit' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_tenant', { defaultValue: 'Tenant' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_invoice', { defaultValue: 'Invoice' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_due_date', { defaultValue: 'Due' })}</th>
                      <th className="px-3 py-2 text-start">{t('leasing.col_age', { defaultValue: 'Overdue' })}</th>
                      <th className="px-3 py-2 text-end">{t('leasing.col_paid', { defaultValue: 'Paid' })}</th>
                      <th className="px-3 py-2 text-end">{t('leasing.col_outstanding', { defaultValue: 'Outstanding' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(arrearsQ.data?.items ?? []).map((r) => (
                      <tr key={r.invoice_id} className="border-b border-border-light last:border-0">
                        <td className="px-3 py-2">
                          <Link className="text-oe-blue hover:underline" to={`/leasing/${r.lease_id}`}>
                            {r.code}
                          </Link>
                        </td>
                        <td className="px-3 py-2">{r.unit_label}</td>
                        <td className="px-3 py-2">{r.tenant_name}</td>
                        <td className="px-3 py-2">{r.invoice_number}</td>
                        <td className="px-3 py-2">{r.due_date ? fmtDate(r.due_date) : '–'}</td>
                        <td className="px-3 py-2">
                          <Badge variant={r.bucket === 'over_90' || r.bucket === '61_90' ? 'error' : 'warning'} size="sm">
                            {bucketLabel(r.bucket, t)}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(r.paid, r.currency)}</td>
                        <td className="px-3 py-2 text-end font-semibold tabular-nums">{fmtCurrency(r.due, r.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    {Object.entries(arrearsQ.data?.totals ?? {}).map(([cur, b]) => (
                      <tr key={cur} className="font-semibold">
                        <td className="px-3 py-2" colSpan={7}>
                          {t('leasing.total', { defaultValue: 'Total' })}
                        </td>
                        <td className="px-3 py-2 text-end tabular-nums">{fmtCurrency(b.total ?? '0', cur)}</td>
                      </tr>
                    ))}
                  </tfoot>
                </table>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
