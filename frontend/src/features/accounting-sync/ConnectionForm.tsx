// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One form for creating a connection and for editing its settings. Which fields
 * show depends on the provider: live providers (Xero, QuickBooks) ask for the
 * app credentials and the tenant, DATEV for the consultant and client numbers,
 * the journal for its column list. The client secret is write-only: it is never
 * filled in, and an empty box on save means "keep the stored secret".
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, WideModalField } from '@/shared/ui';
import {
  LIVE_PROVIDERS,
  type Connection,
  type ConnectionCreate,
  type ConnectionSettings,
  type ConnectionUpdate,
  type Provider,
  type TemplateCatalog,
} from './api';
import { columnLabel } from './labels';
import { Toggle, inputCls } from './ui';

export interface ProjectOption {
  id: string;
  name: string;
}

export interface FormState {
  name: string;
  country_code: string;
  chart_template: string;
  base_currency: string;
  is_sandbox: boolean;
  client_id: string;
  client_secret: string;
  external_tenant_id: string;
  lock_date: string;
  project_ids: string[];
  auto_push: boolean;
  consultant_number: string;
  client_number: string;
  journal_columns: string[];
}

function initialState(c: Connection | null, projects: ProjectOption[]): FormState {
  const s = c?.settings ?? {};
  return {
    name: c?.name ?? '',
    country_code: c?.country_code ?? '',
    chart_template: c?.chart_template ?? '',
    base_currency: c?.base_currency ?? '',
    is_sandbox: c?.is_sandbox ?? false,
    client_id: c?.client_id ?? '',
    client_secret: '',
    external_tenant_id: c?.external_tenant_id ?? '',
    lock_date: c?.lock_date ?? '',
    project_ids: c ? c.project_ids : projects.length === 1 ? projects.map((p) => p.id) : [],
    auto_push: s.auto_push === true,
    consultant_number: typeof s.consultant_number === 'string' ? s.consultant_number : '',
    client_number: typeof s.client_number === 'string' ? s.client_number : '',
    journal_columns: Array.isArray(s.journal_columns) ? s.journal_columns : [],
  };
}

/** Pure: the request body a form state turns into. Exported for the tests. */
export function buildBody(
  provider: Provider,
  f: FormState,
  existing: Connection | null,
): ConnectionCreate & ConnectionUpdate {
  const settings: ConnectionSettings = { ...(existing?.settings ?? {}) };
  if (LIVE_PROVIDERS.includes(provider)) settings.auto_push = f.auto_push;
  if (provider === 'datev') {
    settings.consultant_number = f.consultant_number.trim();
    settings.client_number = f.client_number.trim();
  }
  if (provider === 'journal') settings.journal_columns = f.journal_columns;
  const body: ConnectionCreate & ConnectionUpdate = {
    name: f.name.trim(),
    provider,
    base_currency: f.base_currency.trim().toUpperCase(),
    is_sandbox: f.is_sandbox,
    project_ids: f.project_ids,
    settings,
  };
  if (f.country_code.trim()) body.country_code = f.country_code.trim().toUpperCase();
  if (f.chart_template) body.chart_template = f.chart_template;
  if (LIVE_PROVIDERS.includes(provider)) {
    if (f.client_id.trim()) body.client_id = f.client_id.trim();
    if (f.client_secret) body.client_secret = f.client_secret;
    if (f.external_tenant_id.trim()) body.external_tenant_id = f.external_tenant_id.trim();
  }
  if (f.lock_date) body.lock_date = f.lock_date;
  else if (existing?.lock_date) body.clear_lock_date = true;
  return body;
}

export function ConnectionForm({
  provider,
  existing,
  projects,
  catalog,
  pending,
  readOnly,
  submitLabel,
  onSubmit,
  onCancel,
  extraActions,
}: {
  provider: Provider;
  existing: Connection | null;
  projects: ProjectOption[];
  catalog: TemplateCatalog | undefined;
  pending: boolean;
  readOnly: boolean;
  submitLabel: string;
  onSubmit: (body: ConnectionCreate & ConnectionUpdate) => void;
  onCancel?: () => void;
  extraActions?: React.ReactNode;
}) {
  const { t } = useTranslation();
  const [f, setF] = useState<FormState>(() => initialState(existing, projects));
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));
  const live = LIVE_PROVIDERS.includes(provider);
  const valid = f.name.trim() !== '' && /^[A-Za-z]{3}$/.test(f.base_currency.trim());
  const columns = useMemo(() => catalog?.journal_columns ?? [], [catalog]);

  const toggleIn = (list: string[], v: string): string[] => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid && !readOnly) onSubmit(buildBody(provider, f, existing));
      }}
    >
      <fieldset disabled={readOnly || pending} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <WideModalField label={t('accountingSync.field.name', { defaultValue: 'Connection name' })} required>
          <input className={inputCls} value={f.name} onChange={(e) => set('name', e.target.value)} autoFocus={!existing} />
        </WideModalField>
        <WideModalField
          label={t('accountingSync.field.currency', { defaultValue: 'Books currency' })}
          hint={t('accountingSync.field.currency_hint', { defaultValue: 'Three-letter code, for example EUR' })}
          required
        >
          <input className={inputCls} maxLength={3} value={f.base_currency} onChange={(e) => set('base_currency', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('accountingSync.field.country', { defaultValue: 'Country' })} hint={t('accountingSync.field.country_hint', { defaultValue: 'Two-letter code, for example DE. Picks the matching chart of accounts.' })}>
          <input className={inputCls} maxLength={2} value={f.country_code} onChange={(e) => set('country_code', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('accountingSync.field.template', { defaultValue: 'Chart of accounts template' })}>
          <select className={inputCls} value={f.chart_template} onChange={(e) => set('chart_template', e.target.value)}>
            <option value="">{t('accountingSync.field.template_none', { defaultValue: 'None yet' })}</option>
            {(catalog?.templates ?? []).map((tpl) => (
              <option key={tpl.key} value={tpl.key}>{tpl.label}</option>
            ))}
          </select>
        </WideModalField>

        {live && (
          <>
            <WideModalField label={t('accountingSync.field.client_id', { defaultValue: 'Client ID' })}>
              <input className={inputCls} value={f.client_id} onChange={(e) => set('client_id', e.target.value)} autoComplete="off" />
            </WideModalField>
            <WideModalField
              label={t('accountingSync.field.client_secret', { defaultValue: 'Client secret' })}
              hint={
                existing?.has_client_secret
                  ? t('accountingSync.field.secret_set', { defaultValue: 'Set. Leave empty to keep it.' })
                  : t('accountingSync.field.secret_not_set', { defaultValue: 'Not set' })
              }
            >
              <input
                type="password"
                className={inputCls}
                value={f.client_secret}
                onChange={(e) => set('client_secret', e.target.value)}
                autoComplete="new-password"
                data-testid="accounting-sync-secret"
              />
            </WideModalField>
            <WideModalField
              label={t('accountingSync.field.tenant', { defaultValue: 'Tenant or realm ID' })}
              hint={t('accountingSync.field.tenant_hint', { defaultValue: 'Filled in by the authorisation; set it by hand only if you know it.' })}
            >
              <input className={inputCls} value={f.external_tenant_id} onChange={(e) => set('external_tenant_id', e.target.value)} />
            </WideModalField>
            <div className="flex items-end pb-2">
              <Toggle
                checked={f.is_sandbox}
                onChange={(v) => set('is_sandbox', v)}
                label={t('accountingSync.field.sandbox', { defaultValue: 'Sandbox (test company)' })}
                hint={t('accountingSync.field.sandbox_hint', { defaultValue: 'Nothing reaches your real books.' })}
              />
            </div>
          </>
        )}

        {provider === 'datev' && (
          <>
            <WideModalField label={t('accountingSync.field.consultant_number', { defaultValue: 'Consultant number' })}>
              <input className={inputCls} inputMode="numeric" value={f.consultant_number} onChange={(e) => set('consultant_number', e.target.value)} />
            </WideModalField>
            <WideModalField label={t('accountingSync.field.client_number', { defaultValue: 'Client number' })}>
              <input className={inputCls} inputMode="numeric" value={f.client_number} onChange={(e) => set('client_number', e.target.value)} />
            </WideModalField>
          </>
        )}

        <WideModalField
          label={t('accountingSync.field.lock_date', { defaultValue: 'Books closed through' })}
          hint={t('accountingSync.field.lock_date_hint', { defaultValue: 'Documents dated on or before this day are not sent.' })}
        >
          <input type="date" className={inputCls} value={f.lock_date} onChange={(e) => set('lock_date', e.target.value)} />
        </WideModalField>
        {live && (
          <div className="flex items-end pb-2">
            <Toggle
              checked={f.auto_push}
              onChange={(v) => set('auto_push', v)}
              label={t('accountingSync.field.auto_push', { defaultValue: 'Send automatically on approval' })}
              hint={t('accountingSync.field.auto_push_hint', { defaultValue: 'Otherwise you push by hand from the Sync tab.' })}
            />
          </div>
        )}

        <WideModalField
          span={2}
          label={t('accountingSync.field.projects', { defaultValue: 'Projects in scope' })}
          hint={t('accountingSync.field.projects_hint', { defaultValue: 'Leave all unticked to include every project.' })}
        >
          {projects.length === 0 ? (
            <p className="text-sm text-content-tertiary">{t('accountingSync.field.no_projects', { defaultValue: 'No projects yet.' })}</p>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {projects.map((p) => (
                <label key={p.id} className="flex items-center gap-2 text-sm text-content-primary">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                    checked={f.project_ids.includes(p.id)}
                    onChange={() => set('project_ids', toggleIn(f.project_ids, p.id))}
                  />
                  {p.name}
                </label>
              ))}
            </div>
          )}
        </WideModalField>

        {provider === 'journal' && (
          <WideModalField
            span={2}
            label={t('accountingSync.field.journal_columns', { defaultValue: 'Journal columns' })}
            hint={t('accountingSync.field.journal_columns_hint', { defaultValue: 'Leave all unticked to export every column.' })}
          >
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {columns.map((c) => (
                <label key={c} className="flex items-center gap-2 text-sm text-content-primary">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                    checked={f.journal_columns.includes(c)}
                    onChange={() => set('journal_columns', toggleIn(f.journal_columns, c))}
                  />
                  {columnLabel(t, c)}
                </label>
              ))}
            </div>
          </WideModalField>
        )}
      </fieldset>

      <div className="flex flex-wrap items-center justify-end gap-2">
        {extraActions}
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        )}
        {!readOnly && (
          <Button type="submit" variant="primary" loading={pending} disabled={!valid}>
            {submitLabel}
          </Button>
        )}
      </div>
    </form>
  );
}
