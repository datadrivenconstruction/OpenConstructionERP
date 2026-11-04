// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings > Identity: connect the company identity provider over SCIM 2.0.
 *
 * The admin pastes the base URL and a token into the IdP; people then appear,
 * change role through the groups mapped here, and lose access when they leave.
 * The token is a normal API key with the `scim` scope and is shown once.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Copy, KeyRound } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, Skeleton } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui/Badge';
import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

type Source = 'scim' | 'oidc' | 'local';

interface ScimUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  source: Source;
  last_sync_at: string | null;
}

interface ScimGroup {
  id: string;
  display_name: string;
  role: string | null;
  member_count: number;
}

interface ScimStatus {
  base_path: string;
  users_provisioned: number;
  last_change_at: string | null;
  allow_admin_groups: boolean;
  sso_enforced_domains: string[];
  users: ScimUser[];
  groups: ScimGroup[];
}

interface CreatedKey {
  key: string;
}

const ROLES = ['admin', 'manager', 'editor', 'viewer'] as const;
const SOURCE_VARIANT: Record<Source, BadgeVariant> = { scim: 'blue', oidc: 'purple', local: 'neutral' };
const STATUS_KEY = ['scim', 'status'];

function formatWhen(iso: string | null, lang: string): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }).format(d);
}

export function ScimPanel() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [token, setToken] = useState<string | null>(null);
  const [copied, setCopied] = useState<'url' | 'token' | null>(null);

  const baseUrl = `${window.location.origin}/scim/v2`;
  const { data, isLoading, isError } = useQuery({
    queryKey: STATUS_KEY,
    queryFn: () => apiGet<ScimStatus>('/v1/scim/status/'),
  });

  const generate = useMutation({
    mutationFn: () =>
      apiPost<CreatedKey>('/v1/users/me/api-keys/', {
        name: 'SCIM provisioning',
        description: 'Identity provider provisioning (SCIM 2.0)',
        permissions: ['scim'],
      }),
    onSuccess: (res) => setToken(res.key),
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const setRole = useMutation({
    mutationFn: (v: { id: string; role: string | null }) =>
      apiPatch<ScimGroup>(`/v1/scim/groups/${v.id}/`, { role: v.role }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: STATUS_KEY });
      addToast({ type: 'success', title: t('scim.role_saved', { defaultValue: 'Group role saved' }) });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const copy = async (what: 'url' | 'token', value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(what);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      /* clipboard may be blocked; the value stays selectable on screen */
    }
  };

  const roleLabel = (role: string) => t(`scim.role_${role}`, { defaultValue: role });

  return (
    <div className="space-y-4" data-testid="scim-panel">
      <Card>
        <CardHeader
          title={t('scim.title', { defaultValue: 'User provisioning (SCIM)' })}
          subtitle={t('scim.subtitle', {
            defaultValue: 'Your identity provider creates people, changes their role and removes access when they leave.',
          })}
        />
        <CardContent className="space-y-4">
          <div>
            <div className="text-xs font-medium text-content-secondary">
              {t('scim.base_url', { defaultValue: 'SCIM base URL' })}
            </div>
            <div className="mt-1 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-lg bg-surface-secondary px-3 py-1.5 text-sm" data-testid="scim-base-url">
                {baseUrl}
              </code>
              <Button
                variant="secondary"
                size="sm"
                icon={copied === 'url' ? <Check size={14} /> : <Copy size={14} />}
                onClick={() => void copy('url', baseUrl)}
              >
                {copied === 'url' ? t('scim.copied', { defaultValue: 'Copied' }) : t('scim.copy', { defaultValue: 'Copy' })}
              </Button>
            </div>
          </div>

          <div>
            <Button
              variant="primary"
              size="sm"
              icon={<KeyRound size={14} />}
              loading={generate.isPending}
              onClick={() => generate.mutate()}
            >
              {t('scim.generate_token', { defaultValue: 'Generate token' })}
            </Button>
            {token && (
              <div className="mt-3 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg p-3" role="status" data-testid="scim-token-box">
                <p className="text-sm font-medium text-content-primary">
                  {t('scim.token_once', { defaultValue: 'Copy this token now. It is shown only once.' })}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 break-all text-sm" data-testid="scim-token">
                    {token}
                  </code>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={copied === 'token' ? <Check size={14} /> : <Copy size={14} />}
                    onClick={() => void copy('token', token)}
                  >
                    {copied === 'token' ? t('scim.copied', { defaultValue: 'Copied' }) : t('scim.copy', { defaultValue: 'Copy' })}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setToken(null)}>
                    {t('scim.token_done', { defaultValue: 'I have saved it' })}
                  </Button>
                </div>
              </div>
            )}
          </div>

          <p className="text-sm text-content-secondary" data-testid="scim-status-line">
            {data && data.users_provisioned > 0
              ? t('scim.status', {
                  defaultValue: '{{count}} users provisioned, last change {{time}}',
                  count: data.users_provisioned,
                  time: formatWhen(data.last_change_at, i18n.language),
                })
              : t('scim.status_none', { defaultValue: 'No users provisioned yet' })}
          </p>

          <ul className="list-disc space-y-0.5 pl-5 text-xs text-content-secondary" data-testid="scim-hint">
            <li>{t('scim.hint_entra', { defaultValue: 'Entra: Enterprise application, Provisioning, Automatic. Paste the URL and token.' })}</li>
            <li>{t('scim.hint_okta', { defaultValue: 'Okta: Application, Provisioning, SCIM connector. Base URL, bearer token.' })}</li>
            <li>{t('scim.hint_keycloak', { defaultValue: 'Keycloak: use a SCIM provisioning extension with the same URL and token.' })}</li>
          </ul>
        </CardContent>
      </Card>

      {isLoading && <Skeleton className="h-40 w-full rounded-2xl" />}
      {isError && (
        <p className="text-sm text-semantic-error" role="alert">
          {t('scim.load_failed', { defaultValue: 'Could not load the provisioning status.' })}
        </p>
      )}

      {data && (
        <>
          <Card>
            <CardHeader title={t('scim.groups_title', { defaultValue: 'Groups and roles' })} />
            <CardContent>
              {data.groups.length === 0 ? (
                <p className="text-sm text-content-secondary">
                  {t('scim.groups_empty', { defaultValue: 'No groups yet. They appear when the identity provider pushes them.' })}
                </p>
              ) : (
                <table className="w-full text-sm" data-testid="scim-groups">
                  <thead>
                    <tr className="text-left text-xs text-content-secondary">
                      <th className="py-1 pr-3 font-medium">{t('scim.col_group', { defaultValue: 'Group' })}</th>
                      <th className="py-1 pr-3 font-medium">{t('scim.col_members', { defaultValue: 'Members' })}</th>
                      <th className="py-1 font-medium">{t('scim.col_role', { defaultValue: 'Role' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.groups.map((g) => (
                      <tr key={g.id} className="border-t border-border-light">
                        <td className="py-1.5 pr-3">{g.display_name}</td>
                        <td className="py-1.5 pr-3">{g.member_count}</td>
                        <td className="py-1.5">
                          <select
                            aria-label={t('scim.role_for', { defaultValue: 'Role for {{name}}', name: g.display_name })}
                            className="rounded-lg border border-border bg-surface-primary px-2 py-1 text-sm"
                            value={g.role ?? ''}
                            disabled={setRole.isPending}
                            onChange={(e) => setRole.mutate({ id: g.id, role: e.target.value || null })}
                          >
                            <option value="">{t('scim.role_none', { defaultValue: 'No role (label only)' })}</option>
                            {ROLES.map((r) => (
                              <option key={r} value={r} disabled={r === 'admin' && !data.allow_admin_groups && g.role !== 'admin'}>
                                {roleLabel(r)}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {!data.allow_admin_groups && (
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('scim.admin_disabled', { defaultValue: 'Mapping a group to admin is off. Set SCIM_ALLOW_ADMIN_GROUPS=true to allow it.' })}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader title={t('scim.users_title', { defaultValue: 'People' })} />
            <CardContent>
              <table className="w-full text-sm" data-testid="scim-users">
                <thead>
                  <tr className="text-left text-xs text-content-secondary">
                    <th className="py-1 pr-3 font-medium">{t('scim.col_user', { defaultValue: 'User' })}</th>
                    <th className="py-1 pr-3 font-medium">{t('scim.col_source', { defaultValue: 'Source' })}</th>
                    <th className="py-1 pr-3 font-medium">{t('scim.col_role', { defaultValue: 'Role' })}</th>
                    <th className="py-1 font-medium">{t('scim.col_last_sync', { defaultValue: 'Last sync' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.users.map((u) => (
                    <tr key={u.id} className="border-t border-border-light">
                      <td className="py-1.5 pr-3">
                        <div className={u.is_active ? '' : 'text-content-tertiary line-through'}>{u.email}</div>
                        {u.full_name && <div className="text-xs text-content-secondary">{u.full_name}</div>}
                      </td>
                      <td className="py-1.5 pr-3">
                        <Badge variant={SOURCE_VARIANT[u.source]} size="sm">
                          {t(`scim.source_${u.source}`, { defaultValue: u.source === 'local' ? 'Local' : u.source.toUpperCase() })}
                        </Badge>
                        {!u.is_active && (
                          <Badge variant="warning" size="sm" className="ml-1">
                            {t('scim.inactive', { defaultValue: 'Inactive' })}
                          </Badge>
                        )}
                      </td>
                      <td className="py-1.5 pr-3">{roleLabel(u.role)}</td>
                      <td className="py-1.5 text-xs text-content-secondary">{formatWhen(u.last_sync_at, i18n.language)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
