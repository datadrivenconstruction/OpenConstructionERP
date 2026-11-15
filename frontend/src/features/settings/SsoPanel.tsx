// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings > Identity: single sign-on providers (OIDC and SAML 2.0).
 *
 * Each provider gets a login button; people are created on first sign-in and
 * their role follows the IdP groups mapped here. SAML appears only when the
 * server has the optional [sso] extra installed.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, Input, Skeleton } from '@/shared/ui';
import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

type Protocol = 'oidc' | 'saml';
const ROLES = ['manager', 'editor', 'viewer', 'admin'] as const;

interface Provider {
  id: string;
  slug: string;
  display_name: string;
  protocol: Protocol;
  enabled: boolean;
  tenant_id: string | null;
  email_domains: string[];
  auto_create_users: boolean;
  default_role: string;
  group_attribute: string;
  group_role_map: Record<string, string>;
  allow_admin_mapping: boolean;
  clock_skew_seconds: number;
  oidc_issuer: string | null;
  oidc_client_id: string | null;
  oidc_scopes: string;
  has_client_secret: boolean;
  saml_idp_entity_id: string | null;
  saml_idp_sso_url: string | null;
  saml_idp_cert: string | null;
  saml_email_attribute: string;
  saml_name_attribute: string;
  sp_entity_id: string | null;
  acs_url: string | null;
  metadata_url: string | null;
}

interface Draft {
  id?: string;
  slug: string;
  display_name: string;
  protocol: Protocol;
  enabled: boolean;
  tenant_id: string;
  email_domains: string;
  auto_create_users: boolean;
  default_role: string;
  group_attribute: string;
  group_role_map: string;
  allow_admin_mapping: boolean;
  clock_skew_seconds: number;
  oidc_issuer: string;
  oidc_client_id: string;
  oidc_client_secret: string;
  saml_idp_entity_id: string;
  saml_idp_sso_url: string;
  saml_idp_cert: string;
  saml_email_attribute: string;
}

const LIST_KEY = ['sso', 'providers'];

function emptyDraft(protocol: Protocol): Draft {
  return {
    slug: '',
    display_name: '',
    protocol,
    enabled: true,
    tenant_id: '',
    email_domains: '',
    auto_create_users: true,
    default_role: 'viewer',
    group_attribute: 'groups',
    group_role_map: '',
    allow_admin_mapping: false,
    clock_skew_seconds: 120,
    oidc_issuer: '',
    oidc_client_id: '',
    oidc_client_secret: '',
    saml_idp_entity_id: '',
    saml_idp_sso_url: '',
    saml_idp_cert: '',
    saml_email_attribute: 'email',
  };
}

function toDraft(p: Provider): Draft {
  return {
    ...emptyDraft(p.protocol),
    id: p.id,
    slug: p.slug,
    display_name: p.display_name,
    enabled: p.enabled,
    tenant_id: p.tenant_id ?? '',
    email_domains: p.email_domains.join(', '),
    auto_create_users: p.auto_create_users,
    default_role: p.default_role,
    group_attribute: p.group_attribute,
    group_role_map: Object.entries(p.group_role_map).map(([g, r]) => `${g}=${r}`).join('\n'),
    allow_admin_mapping: p.allow_admin_mapping,
    clock_skew_seconds: p.clock_skew_seconds,
    oidc_issuer: p.oidc_issuer ?? '',
    oidc_client_id: p.oidc_client_id ?? '',
    saml_idp_entity_id: p.saml_idp_entity_id ?? '',
    saml_idp_sso_url: p.saml_idp_sso_url ?? '',
    saml_idp_cert: p.saml_idp_cert ?? '',
    saml_email_attribute: p.saml_email_attribute,
  };
}

function toPayload(d: Draft): Record<string, unknown> {
  const map: Record<string, string> = {};
  for (const line of d.group_role_map.split('\n')) {
    const [g, r] = line.split('=').map((s) => s.trim());
    if (g && r) map[g] = r;
  }
  const out: Record<string, unknown> = {
    display_name: d.display_name,
    enabled: d.enabled,
    tenant_id: d.tenant_id.trim() || null,
    email_domains: d.email_domains.split(',').map((s) => s.trim()).filter(Boolean),
    auto_create_users: d.auto_create_users,
    default_role: d.default_role,
    group_attribute: d.group_attribute,
    group_role_map: map,
    allow_admin_mapping: d.allow_admin_mapping,
    clock_skew_seconds: Number(d.clock_skew_seconds),
  };
  if (d.protocol === 'oidc') {
    Object.assign(out, { oidc_issuer: d.oidc_issuer, oidc_client_id: d.oidc_client_id });
    if (d.oidc_client_secret) out.oidc_client_secret = d.oidc_client_secret;
  } else {
    Object.assign(out, {
      saml_idp_entity_id: d.saml_idp_entity_id,
      saml_idp_sso_url: d.saml_idp_sso_url,
      saml_idp_cert: d.saml_idp_cert,
      saml_email_attribute: d.saml_email_attribute,
    });
  }
  if (!d.id) Object.assign(out, { slug: d.slug, protocol: d.protocol });
  return out;
}

export function SsoPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [draft, setDraft] = useState<Draft | null>(null);

  const caps = useQuery({
    queryKey: ['sso', 'capabilities'],
    queryFn: () => apiGet<{ saml_available: boolean }>('/v1/sso/capabilities/'),
  });
  const list = useQuery({ queryKey: LIST_KEY, queryFn: () => apiGet<Provider[]>('/v1/sso/providers/admin/') });
  const samlAvailable = caps.data?.saml_available ?? false;

  const done = (title: string) => {
    void queryClient.invalidateQueries({ queryKey: LIST_KEY });
    addToast({ type: 'success', title });
  };
  const save = useMutation({
    mutationFn: (d: Draft) =>
      d.id
        ? apiPatch<Provider>(`/v1/sso/providers/admin/${d.id}`, toPayload(d))
        : apiPost<Provider>('/v1/sso/providers/admin/', toPayload(d)),
    onSuccess: () => {
      setDraft(null);
      done(t('sso.saved', { defaultValue: 'Identity provider saved' }));
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/sso/providers/admin/${id}`),
    onSuccess: () => done(t('sso.deleted', { defaultValue: 'Identity provider removed' })),
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const roleLabel = (r: string) => t(`scim.role_${r}`, { defaultValue: r });

  return (
    <Card data-testid="sso-panel">
      <CardHeader
        title={t('sso.title', { defaultValue: 'Single sign-on' })}
        subtitle={t('sso.subtitle', {
          defaultValue: 'Let people sign in with the company identity provider. Accounts are created on first sign-in.',
        })}
      />
      <CardContent className="space-y-4">
        {list.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <ul className="divide-y divide-border-light">
            {(list.data ?? []).map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="font-medium">{p.display_name}</span>
                <Badge variant={p.protocol === 'saml' ? 'purple' : 'blue'}>{p.protocol.toUpperCase()}</Badge>
                {!p.enabled && <Badge variant="neutral">{t('sso.disabled', { defaultValue: 'Disabled' })}</Badge>}
                {p.metadata_url && (
                  <a className="text-xs text-oe-blue hover:underline" href={p.metadata_url} target="_blank" rel="noreferrer">
                    {t('sso.sp_metadata', { defaultValue: 'SP metadata' })}
                  </a>
                )}
                <span className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setDraft(toDraft(p))}>
                    {t('sso.edit', { defaultValue: 'Edit' })}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Trash2 size={14} />}
                    onClick={() => {
                      if (window.confirm(t('sso.confirm_delete', { defaultValue: 'Remove this identity provider?' }))) {
                        remove.mutate(p.id);
                      }
                    }}
                  >
                    {t('sso.delete', { defaultValue: 'Remove' })}
                  </Button>
                </span>
              </li>
            ))}
            {list.data?.length === 0 && (
              <li className="py-2 text-sm text-content-tertiary">
                {t('sso.none', { defaultValue: 'No identity providers yet.' })}
              </li>
            )}
          </ul>
        )}

        {!draft && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setDraft(emptyDraft('oidc'))}>
              {t('sso.add_oidc', { defaultValue: 'Add OpenID Connect' })}
            </Button>
            {samlAvailable ? (
              <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setDraft(emptyDraft('saml'))}>
                {t('sso.add_saml', { defaultValue: 'Add SAML 2.0' })}
              </Button>
            ) : (
              <span className="text-xs text-content-tertiary self-center">
                {t('sso.saml_not_installed', { defaultValue: 'SAML needs the optional [sso] server extra.' })}
              </span>
            )}
          </div>
        )}

        {draft && (
          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(draft);
            }}
          >
            <Input
              label={t('sso.field_name', { defaultValue: 'Button label' })}
              value={draft.display_name}
              required
              onChange={(e) => set('display_name', e.target.value)}
            />
            <Input
              label={t('sso.field_slug', { defaultValue: 'Short name (in URLs)' })}
              value={draft.slug}
              disabled={!!draft.id}
              required
              pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
              onChange={(e) => set('slug', e.target.value.toLowerCase())}
            />
            {draft.protocol === 'oidc' ? (
              <>
                <Input
                  label={t('sso.field_issuer', { defaultValue: 'Issuer URL' })}
                  value={draft.oidc_issuer}
                  placeholder="https://"
                  onChange={(e) => set('oidc_issuer', e.target.value)}
                />
                <Input
                  label={t('sso.field_client_id', { defaultValue: 'Client ID' })}
                  value={draft.oidc_client_id}
                  onChange={(e) => set('oidc_client_id', e.target.value)}
                />
                <Input
                  label={t('sso.field_client_secret', { defaultValue: 'Client secret' })}
                  type="password"
                  autoComplete="new-password"
                  value={draft.oidc_client_secret}
                  hint={draft.id ? t('sso.secret_keep', { defaultValue: 'Leave empty to keep the saved secret.' }) : undefined}
                  onChange={(e) => set('oidc_client_secret', e.target.value)}
                />
              </>
            ) : (
              <>
                <Input
                  label={t('sso.field_idp_entity', { defaultValue: 'IdP entity ID' })}
                  value={draft.saml_idp_entity_id}
                  onChange={(e) => set('saml_idp_entity_id', e.target.value)}
                />
                <Input
                  label={t('sso.field_idp_sso_url', { defaultValue: 'IdP sign-in URL' })}
                  value={draft.saml_idp_sso_url}
                  placeholder="https://"
                  onChange={(e) => set('saml_idp_sso_url', e.target.value)}
                />
                <Input
                  label={t('sso.field_email_attr', { defaultValue: 'Email attribute' })}
                  value={draft.saml_email_attribute}
                  onChange={(e) => set('saml_email_attribute', e.target.value)}
                />
                <label className="sm:col-span-2 text-xs font-medium text-content-secondary">
                  {t('sso.field_idp_cert', { defaultValue: 'IdP signing certificate (PEM)' })}
                  <textarea
                    className="oe-input mt-1 h-28 w-full font-mono text-2xs"
                    value={draft.saml_idp_cert}
                    onChange={(e) => set('saml_idp_cert', e.target.value)}
                  />
                </label>
              </>
            )}
            <Input
              label={t('sso.field_domains', { defaultValue: 'Email domains (comma separated)' })}
              value={draft.email_domains}
              hint={t('sso.domains_hint', { defaultValue: 'Existing accounts are linked only on these domains.' })}
              onChange={(e) => set('email_domains', e.target.value)}
            />
            <Input
              label={t('sso.field_tenant', { defaultValue: 'Tenant (optional)' })}
              value={draft.tenant_id}
              onChange={(e) => set('tenant_id', e.target.value)}
            />
            <Input
              label={t('sso.field_group_attr', { defaultValue: 'Group claim or attribute' })}
              value={draft.group_attribute}
              onChange={(e) => set('group_attribute', e.target.value)}
            />
            <label className="text-xs font-medium text-content-secondary">
              {t('sso.field_default_role', { defaultValue: 'Role for new people' })}
              <select
                className="oe-select mt-1 w-full"
                value={draft.default_role}
                onChange={(e) => set('default_role', e.target.value)}
              >
                {ROLES.filter((r) => r !== 'admin').map((r) => (
                  <option key={r} value={r}>{roleLabel(r)}</option>
                ))}
              </select>
            </label>
            <label className="sm:col-span-2 text-xs font-medium text-content-secondary">
              {t('sso.field_group_map', { defaultValue: 'Group to role, one per line (group=role)' })}
              <textarea
                className="oe-input mt-1 h-20 w-full font-mono text-2xs"
                value={draft.group_role_map}
                placeholder="estimators=editor"
                onChange={(e) => set('group_role_map', e.target.value)}
              />
            </label>
            <Input
              label={t('sso.field_skew', { defaultValue: 'Allowed clock skew (seconds)' })}
              type="number"
              min={0}
              max={600}
              value={draft.clock_skew_seconds}
              onChange={(e) => set('clock_skew_seconds', Number(e.target.value))}
            />
            <div className="flex flex-col gap-2 text-sm">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={draft.enabled} onChange={(e) => set('enabled', e.target.checked)} />
                {t('sso.field_enabled', { defaultValue: 'Show on the login page' })}
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={draft.auto_create_users}
                  onChange={(e) => set('auto_create_users', e.target.checked)}
                />
                {t('sso.field_auto_create', { defaultValue: 'Create accounts on first sign-in' })}
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={draft.allow_admin_mapping}
                  onChange={(e) => set('allow_admin_mapping', e.target.checked)}
                />
                {t('sso.field_allow_admin', { defaultValue: 'Allow a group to grant admin' })}
              </label>
            </div>
            <div className="sm:col-span-2 flex gap-2">
              <Button type="submit" size="sm" variant="primary" loading={save.isPending}>
                {t('sso.save', { defaultValue: 'Save' })}
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setDraft(null)}>
                {t('sso.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
