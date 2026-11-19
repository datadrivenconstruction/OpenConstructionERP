// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The company drawer: identity, address, tax ids, sites, people, documents.
 *
 * Tax id fields come from the company's country (the country data on the
 * server): a German company shows VAT id and tax number, a US company an EIN,
 * an unknown country one free field. A format mismatch is a warning under the
 * field; saving is still allowed.
 *
 * The first person added to any company changes what people see, so it asks
 * once, in plain words, before it does it.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-react';

import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { Badge, Button, ConfirmDialog, Input, SearchableSelect, SideDrawer } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { COMPANY_PROFILE_KEY, getCompanyProfile } from '@/features/settings/companyProfile';

import {
  LEGAL_ENTITIES_KEY,
  legalEntitiesApi,
  type EntityAddress,
  type EntityBank,
  type LegalEntity,
  type LegalEntityInput,
  type MemberRole,
  type TaxIdValue,
} from './api';

interface Props {
  company: LegalEntity | null;
  /** The first company of the install: prefilled from the letterhead. */
  isFirst: boolean;
  canEdit: boolean;
  onClose: () => void;
}

interface Form {
  code: string;
  name: string;
  legal_name: string;
  country_code: string;
  functional_currency: string;
  address: EntityAddress;
  tax_ids: Record<string, string>;
  invoice_prefix: string;
  default_signatory: string;
  bank: EntityBank;
  logo_data_url: string;
  is_active: boolean;
  is_default: boolean;
}

const ROLES: MemberRole[] = ['viewer', 'member', 'admin'];

function formOf(c: LegalEntity | null): Form {
  return {
    code: c?.code ?? '',
    name: c?.name ?? '',
    legal_name: c?.legal_name ?? '',
    country_code: c?.country_code ?? '',
    functional_currency: c?.functional_currency ?? '',
    address: { ...(c?.address ?? {}) },
    tax_ids: Object.fromEntries((c?.tax_ids ?? []).map((r) => [r.scheme, r.value])),
    invoice_prefix: c?.invoice_prefix ?? '',
    default_signatory: c?.default_signatory ?? '',
    bank: { ...(c?.bank ?? {}) },
    logo_data_url: c?.logo_data_url ?? '',
    is_active: c?.is_active ?? true,
    is_default: c?.is_default ?? false,
  };
}

interface UserRow {
  id: string;
  email: string;
  full_name?: string | null;
}

export function CompanyDrawer({ company, isFirst, canEdit, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<Form>(() => formOf(company));
  const [seeded, setSeeded] = useState(company !== null || !isFirst);
  const [advanced, setAdvanced] = useState(false);
  const [site, setSite] = useState({ code: '', name: '', city: '' });
  const [person, setPerson] = useState('');
  const [confirmFirst, setConfirmFirst] = useState(false);

  // The first company starts from the letterhead the firm already typed.
  const profileQ = useQuery({ queryKey: COMPANY_PROFILE_KEY, queryFn: getCompanyProfile, enabled: !seeded });
  if (!seeded && profileQ.data) {
    const lines = (profileQ.data.address || '').split('\n').map((l) => l.trim()).filter(Boolean);
    setSeeded(true);
    setForm((f) => ({
      ...f,
      legal_name: profileQ.data.legal_name || f.legal_name,
      name: f.name || profileQ.data.legal_name,
      address: { line1: lines[0] ?? '', city: lines[1] ?? '' },
    }));
  }

  const country = form.country_code.trim().toUpperCase();
  const schemesQ = useQuery({
    queryKey: [...LEGAL_ENTITIES_KEY, 'tax-schemes', country],
    queryFn: () => legalEntitiesApi.taxSchemes(country),
    enabled: country.length === 2,
    staleTime: Infinity,
  });
  const schemes = schemesQ.data?.schemes ?? [];

  const membersQ = useQuery({
    queryKey: [...LEGAL_ENTITIES_KEY, 'members', company?.id],
    queryFn: () => legalEntitiesApi.members(company!.id),
    enabled: company !== null,
  });
  const usersQ = useQuery({
    queryKey: ['users', 'picker'],
    queryFn: async () => {
      const data = await apiGet<UserRow[] | { items: UserRow[] }>('/v1/users/?limit=100');
      return Array.isArray(data) ? data : data.items;
    },
    enabled: canEdit && company !== null,
    staleTime: 60_000,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: LEGAL_ENTITIES_KEY });
  };
  const fail = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });

  const body = (): LegalEntityInput => {
    const tax_ids: TaxIdValue[] = Object.entries(form.tax_ids)
      .map(([scheme, value]) => ({ scheme, value: value.trim() }))
      .filter((r) => r.value);
    return {
      code: form.code.trim(),
      name: form.name.trim() || form.legal_name.trim(),
      legal_name: form.legal_name.trim() || null,
      country_code: country,
      functional_currency: form.functional_currency.trim().toUpperCase(),
      address: form.address,
      tax_ids,
      invoice_prefix: form.invoice_prefix.trim() || null,
      default_signatory: form.default_signatory.trim() || null,
      bank: Object.values(form.bank).some((v) => (v ?? '').trim()) ? form.bank : null,
      logo_data_url: form.logo_data_url || null,
      is_active: form.is_active,
      ...(form.is_default ? { is_default: true } : {}),
    };
  };

  const saveM = useMutation({
    mutationFn: () => (company ? legalEntitiesApi.update(company.id, body()) : legalEntitiesApi.create(body())),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('legal_entities.saved', { defaultValue: 'Company saved' }) });
      onClose();
    },
    onError: fail,
  });
  const siteM = useMutation({
    mutationFn: () =>
      legalEntitiesApi.addBranch(company!.id, {
        code: site.code.trim(),
        name: site.name.trim(),
        address: site.city.trim() ? { city: site.city.trim() } : null,
      }),
    onSuccess: () => {
      setSite({ code: '', name: '', city: '' });
      refresh();
    },
    onError: fail,
  });
  const removeSiteM = useMutation({
    mutationFn: (branchId: string) => legalEntitiesApi.removeBranch(company!.id, branchId),
    onSuccess: refresh,
    onError: fail,
  });
  const addPersonM = useMutation({
    mutationFn: () => legalEntitiesApi.addMember(company!.id, person, 'member'),
    onSuccess: () => {
      setPerson('');
      setConfirmFirst(false);
      refresh();
      qc.invalidateQueries({ queryKey: ['projects'] });
    },
    onError: fail,
  });
  const roleM = useMutation({
    mutationFn: ({ id, role }: { id: string; role: MemberRole }) =>
      legalEntitiesApi.updateMember(company!.id, id, role),
    onSuccess: refresh,
    onError: fail,
  });
  const removePersonM = useMutation({
    mutationFn: (memberId: string) => legalEntitiesApi.removeMember(company!.id, memberId),
    onSuccess: refresh,
    onError: fail,
  });

  const addPerson = () => {
    if (!person) return;
    // The first membership anywhere changes visibility: say so once, explicitly.
    if (membersQ.data && !membersQ.data.any_members) setConfirmFirst(true);
    else addPersonM.mutate();
  };

  const warningFor = (scheme: string) =>
    company?.warnings.find((w) => w.rule_id === 'entity.tax_id_format' && w.field === `tax_ids.${scheme}`);

  const memberIds = new Set((membersQ.data?.items ?? []).map((m) => m.user_id));
  const userOptions = useMemo(
    () =>
      (usersQ.data ?? [])
        .filter((u) => !memberIds.has(u.id))
        .map((u) => ({ value: u.id, label: u.full_name || u.email, hint: u.email })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [usersQ.data, membersQ.data],
  );

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));
  const setAddress = (key: keyof EntityAddress, value: string) =>
    setForm((f) => ({ ...f, address: { ...f.address, [key]: value } }));
  const ro = !canEdit;
  const schemeLabel: Record<string, string> = {
    vat: t('legal_entities.tax_scheme.vat', { defaultValue: 'VAT ID' }),
    tax_number: t('legal_entities.tax_scheme.tax_number', { defaultValue: 'Tax number' }),
    ein: t('legal_entities.tax_scheme.ein', { defaultValue: 'EIN' }),
    bn: t('legal_entities.tax_scheme.bn', { defaultValue: 'Business number' }),
    other: t('legal_entities.tax_scheme.other', { defaultValue: 'Tax ID' }),
  };
  const roleLabel: Record<MemberRole, string> = {
    viewer: t('legal_entities.role_viewer', { defaultValue: 'Viewer' }),
    member: t('legal_entities.role_member', { defaultValue: 'Member' }),
    admin: t('legal_entities.role_admin', { defaultValue: 'Admin' }),
  };
  const sectionTitle = 'text-2xs font-semibold uppercase tracking-wide text-content-tertiary';

  return (
    <SideDrawer
      open
      onClose={onClose}
      title={company ? company.legal_name || company.name : t('legal_entities.add', { defaultValue: 'Add company' })}
      busy={saveM.isPending}
      headerActions={
        canEdit ? (
          <Button size="sm" onClick={() => saveM.mutate()} loading={saveM.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-5 text-sm" data-testid="company-drawer">
        <section className="space-y-2">
          <h4 className={sectionTitle}>{t('legal_entities.section_identity', { defaultValue: 'Identity' })}</h4>
          <div className="grid grid-cols-2 gap-2">
            <Input
              label={t('legal_entities.field_code', { defaultValue: 'Code' })}
              value={form.code}
              readOnly={ro}
              onChange={(e) => set('code', e.target.value)}
            />
            <Input
              label={t('legal_entities.field_country', { defaultValue: 'Country' })}
              value={form.country_code}
              maxLength={2}
              readOnly={ro}
              onChange={(e) => set('country_code', e.target.value.toUpperCase())}
            />
            <Input
              label={t('legal_entities.display_name', { defaultValue: 'Display name' })}
              value={form.name}
              readOnly={ro}
              onChange={(e) => set('name', e.target.value)}
            />
            <Input
              label={t('legal_entities.legal_name', { defaultValue: 'Legal name' })}
              value={form.legal_name}
              readOnly={ro}
              onChange={(e) => set('legal_name', e.target.value)}
            />
          </div>
        </section>

        <section className="space-y-2">
          <h4 className={sectionTitle}>{t('legal_entities.section_address', { defaultValue: 'Address' })}</h4>
          <Input
            label={t('legal_entities.street', { defaultValue: 'Street' })}
            value={form.address.line1 ?? ''}
            readOnly={ro}
            onChange={(e) => setAddress('line1', e.target.value)}
          />
          <div className="grid grid-cols-3 gap-2">
            <Input
              label={t('legal_entities.postcode', { defaultValue: 'Postal code' })}
              value={form.address.postcode ?? ''}
              readOnly={ro}
              onChange={(e) => setAddress('postcode', e.target.value)}
            />
            <div className="col-span-2">
              <Input
                label={t('legal_entities.city', { defaultValue: 'City' })}
                value={form.address.city ?? ''}
                readOnly={ro}
                onChange={(e) => setAddress('city', e.target.value)}
              />
            </div>
          </div>
        </section>

        <section className="space-y-2">
          <h4 className={sectionTitle}>{t('legal_entities.section_tax_ids', { defaultValue: 'Tax ids' })}</h4>
          {schemes.map((s) => {
            const warning = warningFor(s.scheme);
            const label = schemeLabel[s.scheme] ?? schemeLabel.other!;
            return (
              <Input
                key={s.scheme}
                label={s.mandatory_on_invoice ? `${label} *` : label}
                value={form.tax_ids[s.scheme] ?? ''}
                placeholder={s.example}
                readOnly={ro}
                hint={
                  warning
                    ? t('validation.entity.tax_id_format', {
                        defaultValue: 'Format does not match. Example: {{example}}',
                        example: s.example,
                      })
                    : undefined
                }
                onChange={(e) => setForm((f) => ({ ...f, tax_ids: { ...f.tax_ids, [s.scheme]: e.target.value } }))}
                className="font-mono"
              />
            );
          })}
        </section>

        {company && (
          <section className="space-y-2">
            <h4 className={sectionTitle}>{t('legal_entities.section_sites', { defaultValue: 'Sites' })}</h4>
            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {company.branches.map((b) => (
                <li key={b.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
                  <span>
                    <bdi className="font-mono text-xs">{b.code}</bdi> {b.name}
                    {b.address?.city ? <span className="text-content-tertiary"> · {b.address.city}</span> : null}
                  </span>
                  {canEdit && (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Trash2 size={14} />}
                      aria-label={t('legal_entities.delete_branch', { defaultValue: 'Delete site' })}
                      onClick={() => removeSiteM.mutate(b.id)}
                    />
                  )}
                </li>
              ))}
            </ul>
            {canEdit && (
              <div className="flex items-end gap-2">
                <input
                  className="oe-input w-24"
                  aria-label={t('legal_entities.field_code', { defaultValue: 'Code' })}
                  placeholder={t('legal_entities.field_code', { defaultValue: 'Code' })}
                  value={site.code}
                  onChange={(e) => setSite((s) => ({ ...s, code: e.target.value }))}
                />
                <input
                  className="oe-input flex-1"
                  aria-label={t('legal_entities.field_name', { defaultValue: 'Name' })}
                  placeholder={t('legal_entities.field_name', { defaultValue: 'Name' })}
                  value={site.name}
                  onChange={(e) => setSite((s) => ({ ...s, name: e.target.value }))}
                />
                <input
                  className="oe-input w-28"
                  aria-label={t('legal_entities.city', { defaultValue: 'City' })}
                  placeholder={t('legal_entities.city', { defaultValue: 'City' })}
                  value={site.city}
                  onChange={(e) => setSite((s) => ({ ...s, city: e.target.value }))}
                />
                <Button
                  variant="secondary"
                  icon={<Plus size={14} />}
                  disabled={!site.code.trim() || !site.name.trim()}
                  onClick={() => siteM.mutate()}
                >
                  {t('legal_entities.add_site', { defaultValue: 'Add site' })}
                </Button>
              </div>
            )}
          </section>
        )}

        {company && (
          <section className="space-y-2">
            <h4 className={sectionTitle}>{t('legal_entities.section_people', { defaultValue: 'People' })}</h4>
            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {(membersQ.data?.items ?? []).map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
                  <span>{m.full_name || m.email}</span>
                  <span className="flex items-center gap-1">
                    <select
                      className="oe-select-sm"
                      value={m.role}
                      disabled={ro}
                      aria-label={t('legal_entities.role', { defaultValue: 'Role' })}
                      onChange={(e) => roleM.mutate({ id: m.id, role: e.target.value as MemberRole })}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {roleLabel[r]}
                        </option>
                      ))}
                    </select>
                    {canEdit && (
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Trash2 size={14} />}
                        aria-label={t('legal_entities.remove_person', { defaultValue: 'Remove person' })}
                        onClick={() => removePersonM.mutate(m.id)}
                      />
                    )}
                  </span>
                </li>
              ))}
            </ul>
            {canEdit && (
              <div className="flex items-center gap-2">
                <SearchableSelect
                  className="flex-1"
                  value={person}
                  onChange={setPerson}
                  options={userOptions}
                  loading={usersQ.isLoading}
                  placeholder={t('legal_entities.add_person', { defaultValue: 'Add person' })}
                />
                <Button variant="secondary" icon={<Plus size={14} />} disabled={!person} onClick={addPerson}>
                  {t('legal_entities.add_person', { defaultValue: 'Add person' })}
                </Button>
              </div>
            )}
          </section>
        )}

        <section className="space-y-2">
          <button
            type="button"
            className={`flex items-center gap-1 ${sectionTitle}`}
            aria-expanded={advanced}
            onClick={() => setAdvanced((v) => !v)}
          >
            {advanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {t('legal_entities.section_advanced', { defaultValue: 'Advanced' })}
          </button>
          {advanced && (
            <div className="grid grid-cols-2 gap-2">
              <Input
                label={t('legal_entities.field_currency', { defaultValue: 'Currency' })}
                value={form.functional_currency}
                maxLength={3}
                readOnly={ro}
                onChange={(e) => set('functional_currency', e.target.value.toUpperCase())}
              />
              <Input
                label={t('legal_entities.invoice_prefix', { defaultValue: 'Invoice number prefix' })}
                value={form.invoice_prefix}
                readOnly={ro}
                onChange={(e) => set('invoice_prefix', e.target.value)}
                className="font-mono"
              />
              <Input
                label={t('legal_entities.default_signatory', { defaultValue: 'Signs contracts and letters' })}
                value={form.default_signatory}
                readOnly={ro}
                onChange={(e) => set('default_signatory', e.target.value)}
              />
              <Input
                label={t('legal_entities.bank_name', { defaultValue: 'Bank' })}
                value={form.bank.bank_name ?? ''}
                readOnly={ro}
                onChange={(e) => set('bank', { ...form.bank, bank_name: e.target.value })}
              />
              <Input
                label={t('legal_entities.iban', { defaultValue: 'IBAN or account number' })}
                value={form.bank.iban ?? ''}
                readOnly={ro}
                onChange={(e) => set('bank', { ...form.bank, iban: e.target.value })}
                className="font-mono"
              />
              <Input
                label={t('legal_entities.bic', { defaultValue: 'BIC / SWIFT' })}
                value={form.bank.bic ?? ''}
                readOnly={ro}
                onChange={(e) => set('bank', { ...form.bank, bic: e.target.value })}
                className="font-mono"
              />
              <div className="text-sm">
                <span className="mb-1 block font-medium text-content-primary">
                  {t('legal_entities.logo', { defaultValue: 'Logo on documents' })}
                </span>
                <div className="flex items-center gap-2">
                  {form.logo_data_url && (
                    <img src={form.logo_data_url} alt="" className="h-8 max-w-[8rem] object-contain" />
                  )}
                  {!ro && (
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="text-xs"
                      aria-label={t('legal_entities.logo', { defaultValue: 'Logo on documents' })}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        const reader = new FileReader();
                        reader.onload = () => set('logo_data_url', String(reader.result ?? ''));
                        reader.readAsDataURL(file);
                      }}
                    />
                  )}
                  {!ro && form.logo_data_url && (
                    <Button size="sm" variant="ghost" onClick={() => set('logo_data_url', '')}>
                      {t('legal_entities.logo_remove', { defaultValue: 'Remove logo' })}
                    </Button>
                  )}
                </div>
                <p className="mt-1 text-xs text-content-tertiary">
                  {t('legal_entities.logo_hint', { defaultValue: 'Empty: documents carry the workspace logo.' })}
                </p>
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  disabled={ro || (company?.is_default ?? false)}
                  onChange={(e) => set('is_active', e.target.checked)}
                />
                {t('legal_entities.status_active', { defaultValue: 'Active' })}
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.is_default}
                  disabled={ro || (company?.is_default ?? false)}
                  onChange={(e) => set('is_default', e.target.checked)}
                />
                {t('legal_entities.set_default', { defaultValue: 'Make default' })}
              </label>
            </div>
          )}
        </section>

        {company && (
          <section className="space-y-2">
            <h4 className={sectionTitle}>{t('legal_entities.section_documents', { defaultValue: 'Documents' })}</h4>
            <div className="flex items-center justify-between gap-2">
              {company.has_own_einvoice_settings ? (
                <Badge variant="blue" size="sm">
                  {t('legal_entities.own_settings', { defaultValue: 'Own seller details' })}
                </Badge>
              ) : (
                <Badge variant="neutral" size="sm">
                  {t('legal_entities.uses_defaults', { defaultValue: 'Uses defaults' })}
                </Badge>
              )}
              <Link
                to={`/settings?tab=einvoice&scope=${encodeURIComponent(`entity:${company.id}`)}`}
                className="text-oe-blue hover:underline"
              >
                {t('legal_entities.set_for_company', { defaultValue: 'Set for this company' })}
              </Link>
            </div>
          </section>
        )}
      </div>

      <ConfirmDialog
        open={confirmFirst}
        variant="warning"
        title={t('legal_entities.first_member_title', { defaultValue: 'Limit what people see?' })}
        message={t('legal_entities.first_member_body', {
          defaultValue:
            "From now on, people you add here see only this company's projects and projects they are on the team of. Admins still see everything.",
        })}
        loading={addPersonM.isPending}
        onCancel={() => setConfirmFirst(false)}
        onConfirm={() => addPersonM.mutate()}
      />
    </SideDrawer>
  );
}
