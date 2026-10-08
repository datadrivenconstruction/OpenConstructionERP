// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Legal Entities page.
 *
 * The companies of the group and their branches. Anyone signed in can read
 * the list; the server refuses writes from anyone but an administrator, and
 * the page shows its forms only to one so nobody fills in a form for nothing.
 */

import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, Plus, Trash2 } from 'lucide-react';

import { getErrorMessage } from '@/shared/lib/api';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { Input } from '@/shared/ui/Input';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

import { legalEntitiesApi, type LegalEntity, type LegalEntityInput } from './api';

const QUERY_KEY = ['legal-entities'];

const EMPTY: LegalEntityInput = {
  code: '',
  name: '',
  country_code: '',
  subdivision_code: '',
  functional_currency: '',
  tax_id: '',
  registration_number: '',
  is_default: false,
};

function blankToNull(value: string | null | undefined): string | null {
  const trimmed = (value ?? '').trim();
  return trimmed ? trimmed : null;
}

function EntityForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<LegalEntityInput>(EMPTY);

  const create = useMutation({
    mutationFn: () =>
      legalEntitiesApi.create({
        ...form,
        subdivision_code: blankToNull(form.subdivision_code),
        tax_id: blankToNull(form.tax_id),
        registration_number: blankToNull(form.registration_number),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setForm(EMPTY);
      onDone();
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('legal_entities.save_failed', { defaultValue: 'The legal entity was not saved' }),
        message: getErrorMessage(err),
      }),
  });

  const set = (field: keyof LegalEntityInput) => (e: { target: { value: string } }) =>
    setForm((prev) => ({ ...prev, [field]: e.target.value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <form onSubmit={submit} className="grid gap-3 rounded-lg border border-border-light p-4 sm:grid-cols-2" data-testid="legal-entity-form">
      <Input required label={t('legal_entities.field_code', { defaultValue: 'Code' })} value={form.code} onChange={set('code')} maxLength={32} />
      <Input required label={t('legal_entities.field_name', { defaultValue: 'Name' })} value={form.name} onChange={set('name')} maxLength={255} />
      <Input
        required
        label={t('legal_entities.field_country', { defaultValue: 'Country (ISO code, e.g. DE)' })}
        value={form.country_code}
        onChange={set('country_code')}
        maxLength={2}
      />
      <Input
        label={t('legal_entities.field_subdivision', { defaultValue: 'State or province (ISO 3166-2, optional)' })}
        value={form.subdivision_code ?? ''}
        onChange={set('subdivision_code')}
        maxLength={6}
      />
      <Input
        required
        label={t('legal_entities.field_currency', { defaultValue: 'Functional currency (e.g. EUR)' })}
        value={form.functional_currency}
        onChange={set('functional_currency')}
        maxLength={3}
      />
      <Input label={t('legal_entities.field_tax_id', { defaultValue: 'Tax ID' })} value={form.tax_id ?? ''} onChange={set('tax_id')} maxLength={100} />
      <Input
        label={t('legal_entities.field_registration', { defaultValue: 'Registration number' })}
        value={form.registration_number ?? ''}
        onChange={set('registration_number')}
        maxLength={100}
      />
      <label className="flex items-center gap-2 self-end text-sm text-content-secondary">
        <input
          type="checkbox"
          checked={Boolean(form.is_default)}
          onChange={(e) => setForm((prev) => ({ ...prev, is_default: e.target.checked }))}
        />
        {t('legal_entities.field_default', { defaultValue: 'Default entity for documents that name none' })}
      </label>
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" loading={create.isPending}>
          {t('legal_entities.create', { defaultValue: 'Add legal entity' })}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </form>
  );
}

function BranchList({ entity, canManage }: { entity: LegalEntity; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [country, setCountry] = useState('');

  const onError = (err: unknown) =>
    addToast({
      type: 'error',
      title: t('legal_entities.branch_failed', { defaultValue: 'The branch was not saved' }),
      message: getErrorMessage(err),
    });

  const add = useMutation({
    mutationFn: () =>
      legalEntitiesApi.addBranch(entity.id, { code, name, country_code: blankToNull(country) }),
    onSuccess: (branch) => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setCode('');
      setName('');
      setCountry('');
      if (branch.warnings.length > 0) {
        addToast({
          type: 'warning',
          title: t('legal_entities.branch_abroad', {
            defaultValue: 'This branch is in another country than its company and may need its own registration there.',
          }),
        });
      }
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: (branchId: string) => legalEntitiesApi.removeBranch(entity.id, branchId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
    onError,
  });

  return (
    <div className="mt-2 space-y-1 pl-4">
      {entity.branches.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('legal_entities.no_branches', { defaultValue: 'No branches.' })}
        </p>
      ) : (
        entity.branches.map((b) => (
          <div key={b.id} className="flex items-center gap-2 text-xs text-content-secondary">
            <span className="font-mono">{b.code}</span>
            <span>{b.name}</span>
            <span className="text-content-tertiary">
              {b.country_code}
              {b.subdivision_code ? ` / ${b.subdivision_code}` : ''}
            </span>
            {canManage ? (
              <button
                type="button"
                className="text-content-tertiary hover:text-semantic-error"
                aria-label={t('legal_entities.delete_branch', { defaultValue: 'Delete branch' })}
                onClick={() => remove.mutate(b.id)}
              >
                <Trash2 size={12} />
              </button>
            ) : null}
          </div>
        ))
      )}
      {canManage ? (
        <form
          className="flex flex-wrap items-end gap-2 pt-1"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <Input required value={code} onChange={(e) => setCode(e.target.value)} maxLength={32} placeholder={t('legal_entities.field_code', { defaultValue: 'Code' })} />
          <Input required value={name} onChange={(e) => setName(e.target.value)} maxLength={255} placeholder={t('legal_entities.field_name', { defaultValue: 'Name' })} />
          <Input
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            maxLength={2}
            placeholder={t('legal_entities.branch_country', { defaultValue: 'Country, if not the company’s' })}
          />
          <Button type="submit" size="sm" variant="secondary" loading={add.isPending} icon={<Plus size={14} />}>
            {t('legal_entities.add_branch', { defaultValue: 'Add branch' })}
          </Button>
        </form>
      ) : null}
    </div>
  );
}

export function LegalEntitiesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const canManage = userRole === 'admin' || userRole === 'superuser' || userRole === 'owner';
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<LegalEntity | null>(null);

  const list = useQuery({ queryKey: QUERY_KEY, queryFn: () => legalEntitiesApi.list(true) });

  const makeDefault = useMutation({
    mutationFn: (id: string) => legalEntitiesApi.update(id, { is_default: true }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('legal_entities.save_failed', { defaultValue: 'The legal entity was not saved' }),
        message: getErrorMessage(err),
      }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => legalEntitiesApi.remove(id),
    onSuccess: () => {
      setDeleting(null);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (err) => {
      setDeleting(null);
      addToast({
        type: 'error',
        title: t('legal_entities.delete_failed', { defaultValue: 'The legal entity was not deleted' }),
        message: getErrorMessage(err),
      });
    },
  });

  const items = list.data?.items ?? [];

  return (
    <div className="space-y-4 p-4">
      <PageHeader
        srTitle={t('nav.legal_entities', { defaultValue: 'Legal Entities' })}
        subtitle={t('legal_entities.subtitle', {
          defaultValue:
            'The companies of your group. A project names the company that owns it; one that names none belongs to the default company.',
        })}
        actions={
          canManage && !adding ? (
            <Button onClick={() => setAdding(true)} icon={<Plus size={14} />}>
              {t('legal_entities.create', { defaultValue: 'Add legal entity' })}
            </Button>
          ) : undefined
        }
      />

      {adding ? <EntityForm onDone={() => setAdding(false)} /> : null}

      {list.isError ? (
        <p className="text-sm text-semantic-error">{getErrorMessage(list.error)}</p>
      ) : list.isLoading ? null : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border-light p-8 text-center">
          <Building2 size={24} className="text-content-tertiary" />
          <p className="text-sm text-content-secondary">
            {t('legal_entities.empty', {
              defaultValue: 'No legal entities yet. Add your company to number and tax documents by it.',
            })}
          </p>
        </div>
      ) : (
        <ul className="space-y-3" data-testid="legal-entity-list">
          {items.map((entity) => (
            <li key={entity.id} className="rounded-lg border border-border-light p-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-mono text-sm font-semibold">{entity.code}</span>
                <span className="text-sm">{entity.name}</span>
                <span className="text-xs text-content-tertiary">
                  {entity.country_code}
                  {entity.subdivision_code ? ` / ${entity.subdivision_code}` : ''} · {entity.functional_currency}
                  {entity.tax_id ? ` · ${entity.tax_id}` : ''}
                </span>
                {entity.is_default ? (
                  <span className="rounded bg-oe-blue/10 px-1.5 py-0.5 text-2xs text-oe-blue-text">
                    {t('legal_entities.default_badge', { defaultValue: 'Default' })}
                  </span>
                ) : null}
                {!entity.is_active ? (
                  <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-tertiary">
                    {t('legal_entities.inactive_badge', { defaultValue: 'Inactive' })}
                  </span>
                ) : null}
                {canManage ? (
                  <span className="ml-auto flex gap-2">
                    {!entity.is_default && entity.is_active ? (
                      <Button size="sm" variant="ghost" onClick={() => makeDefault.mutate(entity.id)}>
                        {t('legal_entities.make_default', { defaultValue: 'Make default' })}
                      </Button>
                    ) : null}
                    <Button size="sm" variant="ghost" onClick={() => setDeleting(entity)} icon={<Trash2 size={14} />}>
                      {t('common.delete', { defaultValue: 'Delete' })}
                    </Button>
                  </span>
                ) : null}
              </div>
              <BranchList entity={entity} canManage={canManage} />
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={deleting !== null}
        variant="danger"
        loading={remove.isPending}
        title={t('legal_entities.delete_title', { defaultValue: 'Delete this legal entity?' })}
        message={t('legal_entities.delete_message', {
          defaultValue:
            'Its branches go with it. An entity that still owns projects cannot be deleted; move those projects to another entity first.',
        })}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}
