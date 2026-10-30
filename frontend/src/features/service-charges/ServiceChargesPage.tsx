// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Service charges: owners associations of the active project, with a plain-language
 * explainer of the yearly cycle (keys, budget, demands, year-end reconciliation).
 */
import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Building, Calculator, Network, PieChart, Plus, Receipt, Scale } from 'lucide-react';
import { Button, Card, CollapsibleSection, EmptyState, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { createAssociation, fetchAssociations, type AssociationCreate } from './api';

export const inputCls =
  'w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

function HowItWorks() {
  const { t } = useTranslation();
  const steps = [
    {
      icon: <PieChart size={14} className="text-oe-blue" />,
      title: t('service_charges.flow_1_title', { defaultValue: 'Set the shares' }),
      desc: t('service_charges.flow_1_desc', {
        defaultValue: 'An apportionment key says who pays what part: by floor area, by permille, equally or by agreed percent.',
      }),
    },
    {
      icon: <Calculator size={14} className="text-oe-blue" />,
      title: t('service_charges.flow_2_title', { defaultValue: 'Approve the budget' }),
      desc: t('service_charges.flow_2_desc', {
        defaultValue: 'List the expected yearly costs by category, such as cleaning, insurance or lifts, and approve them.',
      }),
    },
    {
      icon: <Receipt size={14} className="text-oe-blue" />,
      title: t('service_charges.flow_3_title', { defaultValue: 'Raise demands' }),
      desc: t('service_charges.flow_3_desc', {
        defaultValue: 'Each period every owner gets a demand for their share, raised as a draft invoice in finance.',
      }),
    },
    {
      icon: <Scale size={14} className="text-oe-blue" />,
      title: t('service_charges.flow_4_title', { defaultValue: 'Settle the year' }),
      desc: t('service_charges.flow_4_desc', {
        defaultValue: 'At year end the real costs are compared with what each owner paid. Who paid too little gets a bill, who paid too much a refund.',
      }),
    },
  ];
  return (
    <CollapsibleSection
      storageKey="service_charges.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('service_charges.flow_title', { defaultValue: 'How service charges work' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('service_charges.flow_intro', {
          defaultValue:
            'The shared costs of a building are split between the owners of its units. This page keeps the shares, the yearly budget, the demands and the year-end settlement in one place.',
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
        <span className="font-medium text-content-secondary">
          {t('service_charges.flow_connects', { defaultValue: 'Connects with:' })}
        </span>{' '}
        <Link className="text-oe-blue hover:underline" to="/finance">
          {t('service_charges.mod_finance', { defaultValue: 'Finance' })}
        </Link>{' '}
        ·{' '}
        <Link className="text-oe-blue hover:underline" to="/service">
          {t('service_charges.mod_service', { defaultValue: 'Service and maintenance' })}
        </Link>{' '}
        ·{' '}
        <Link className="text-oe-blue hover:underline" to="/contacts">
          {t('service_charges.mod_contacts', { defaultValue: 'Contacts' })}
        </Link>
      </div>
    </CollapsibleSection>
  );
}

function NewAssociationForm({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<AssociationCreate>({
    project_id: projectId,
    name: '',
    currency: '',
    fiscal_year_start_month: 1,
  });
  const mutation = useMutation({
    mutationFn: () => createAssociation({ ...form, currency: form.currency.toUpperCase() }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('service_charges.created', { defaultValue: 'Association created' }) });
      onDone();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('service_charges.save_failed', { defaultValue: 'Could not save' }),
        message: getErrorMessage(e),
      }),
  });
  const ready = form.name.trim() && form.currency.length === 3;
  return (
    <Card padding="sm" data-testid="service-charges-new-form">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          <span>{t('service_charges.f_name', { defaultValue: 'Name' })}</span>
          <input className={inputCls} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          <span>{t('service_charges.f_currency', { defaultValue: 'Currency' })}</span>
          <input
            maxLength={3}
            dir="ltr"
            className={inputCls}
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          <span>{t('service_charges.f_fiscal_start', { defaultValue: 'Financial year starts in month' })}</span>
          <input
            type="number"
            min={1}
            max={12}
            className={inputCls}
            value={form.fiscal_year_start_month}
            onChange={(e) => setForm({ ...form, fiscal_year_start_month: Math.min(12, Math.max(1, Number(e.target.value) || 1)) })}
          />
        </label>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onDone}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button variant="primary" size="sm" disabled={!ready || mutation.isPending} onClick={() => mutation.mutate()}>
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </Card>
  );
}

export function ServiceChargesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const [showNew, setShowNew] = useState(false);
  const listQ = useQuery({
    queryKey: ['service-charges', 'list', projectId],
    queryFn: () => fetchAssociations(projectId),
    enabled: !!projectId,
  });
  const rows = listQ.data ?? [];

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('service_charges.title', { defaultValue: 'Service charges' })}
        subtitle={t('service_charges.subtitle', {
          defaultValue: 'Shared building costs split between owners: budget, demands and the year-end settlement.',
        })}
        actions={
          projectId ? (
            <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setShowNew(true)} data-testid="service-charges-new">
              {t('service_charges.new', { defaultValue: 'New association' })}
            </Button>
          ) : undefined
        }
      />
      <HowItWorks />
      {!projectId ? (
        <RequiresProject>{null}</RequiresProject>
      ) : (
        <>
          {showNew && (
            <NewAssociationForm
              projectId={projectId}
              onDone={() => {
                setShowNew(false);
                qc.invalidateQueries({ queryKey: ['service-charges'] });
              }}
            />
          )}
          {listQ.isLoading ? (
            <SkeletonTable rows={4} columns={3} />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={<Building size={28} />}
              title={t('service_charges.empty_title', { defaultValue: 'No owners association yet' })}
              description={t('service_charges.empty_desc', {
                defaultValue: 'Create one for the building, then add the shares of its units.',
              })}
            />
          ) : (
            <Card padding="none">
              <ul className="divide-y divide-border-light">
                {rows.map((a) => (
                  <li key={a.id}>
                    <Link
                      to={`/service-charges/${a.id}`}
                      className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-surface-secondary/50"
                    >
                      <span className="flex items-center gap-2 text-sm font-medium text-content-primary">
                        <Building size={15} className="text-oe-blue" />
                        {a.name}
                      </span>
                      <span className="flex items-center gap-3 text-xs text-content-tertiary">
                        <span dir="ltr">{a.currency}</span>
                        <ArrowRight size={14} className="rtl:rotate-180" />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
