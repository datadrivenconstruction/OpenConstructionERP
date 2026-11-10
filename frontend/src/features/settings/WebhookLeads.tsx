// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * WebhookLeads — Settings → Modules admin UI for the oe_webhook_leads
 * backend module (incoming webhook → CRM lead).
 *
 * Lets an admin/manager:
 *   • list / create / edit / delete webhook sources
 *   • see the ingestion URL + a reveal-once secret on create / rotate
 *   • manage the payload-mapping rules of the selected source
 *   • view the recent ingestion audit log (accepted / rejected / error)
 *
 * i18n: per session convention we DO NOT edit the shared locale files
 * here — every string uses inline `t(key, { defaultValue })`.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Trash2,
  RefreshCw,
  KeyRound,
  Copy,
  ListChecks,
  ScrollText,
} from 'lucide-react';
import { Card, Badge, Button, ConfirmDialog, Input } from '@/shared/ui';
import { copyToClipboard } from '@/shared/lib/browser';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface WebhookSource {
  id: string;
  name: string;
  slug: string;
  auth_method: 'api_key' | 'hmac' | 'jwt';
  project_id: string | null;
  ip_allowlist: string[];
  is_active: boolean;
  rate_limit_per_min: number;
  default_lead_source: string;
  created_at: string;
}

interface WebhookSourceCreated extends WebhookSource {
  secret: string;
  ingestion_url: string;
}

interface PayloadMapping {
  id: string;
  source_id: string;
  target_field: string;
  source_path: string;
  transform: string | null;
  required: boolean;
}

interface WebhookLog {
  id: string;
  source_id: string | null;
  source_slug: string;
  received_at: string | null;
  remote_ip: string;
  status: 'accepted' | 'rejected' | 'error';
  http_status: number;
  error_message: string;
  created_lead_id: string | null;
  created_at: string;
}

const BASE = '/v1/webhook-leads';
const TARGET_FIELDS = [
  'contact_name',
  'contact_email',
  'contact_phone',
  'source',
  'qualification_notes',
];
const TRANSFORMS = ['', 'lower', 'upper', 'strip', 'title', 'str'];

/* ── Component ─────────────────────────────────────────────────────────── */

export function WebhookLeads() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [revealedSecret, setRevealedSecret] = useState<{
    url: string;
    secret: string;
  } | null>(null);

  // Create-source form state.
  const [newName, setNewName] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [newAuth, setNewAuth] = useState<'api_key' | 'hmac' | 'jwt'>('api_key');
  const [newIps, setNewIps] = useState('');
  const [newRate, setNewRate] = useState(60);

  // New-mapping form state.
  const [mapField, setMapField] = useState('contact_name');
  const [mapPath, setMapPath] = useState('');
  const [mapTransform, setMapTransform] = useState('');
  const [mapRequired, setMapRequired] = useState(false);

  const sourcesQ = useQuery({
    queryKey: ['webhook-leads', 'sources'],
    queryFn: () => apiGet<WebhookSource[]>(`${BASE}/sources/`),
  });

  const mappingsQ = useQuery({
    queryKey: ['webhook-leads', 'mappings', selectedId],
    queryFn: () =>
      apiGet<PayloadMapping[]>(`${BASE}/sources/${selectedId}/mappings/`),
    enabled: !!selectedId,
  });

  const logsQ = useQuery({
    queryKey: ['webhook-leads', 'logs', selectedId],
    queryFn: () =>
      apiGet<WebhookLog[]>(
        `${BASE}/logs/${selectedId ? `?source_id=${selectedId}` : ''}`,
      ),
  });

  const createSource = useMutation({
    mutationFn: () =>
      apiPost<WebhookSourceCreated>(`${BASE}/sources/`, {
        name: newName.trim(),
        slug: newSlug.trim(),
        auth_method: newAuth,
        ip_allowlist: newIps
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        rate_limit_per_min: newRate,
      }),
    onSuccess: (created) => {
      setRevealedSecret({ url: created.ingestion_url, secret: created.secret });
      setNewName('');
      setNewSlug('');
      setNewIps('');
      qc.invalidateQueries({ queryKey: ['webhook-leads', 'sources'] });
      addToast({
        type: 'success',
        title: t('webhook_leads.created', { defaultValue: 'Webhook source created' }),
      });
    },
    onError: (e: unknown) =>
      addToast({
        type: 'error',
        title: t('webhook_leads.create_failed', { defaultValue: 'Create failed' }),
        message: e instanceof Error ? e.message : String(e),
      }),
  });

  const rotateSecret = useMutation({
    mutationFn: (id: string) =>
      apiPost<{ id: string; secret: string; ingestion_url: string }>(
        `${BASE}/sources/${id}/rotate-secret`,
      ),
    onSuccess: (r) =>
      setRevealedSecret({ url: r.ingestion_url, secret: r.secret }),
  });

  const toggleActive = useMutation({
    mutationFn: (src: WebhookSource) =>
      apiPatch<WebhookSource>(`${BASE}/sources/${src.id}`, {
        is_active: !src.is_active,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['webhook-leads', 'sources'] }),
  });

  const deleteSource = useMutation({
    mutationFn: (id: string) => apiDelete(`${BASE}/sources/${id}`),
    onSuccess: () => {
      setSelectedId(null);
      qc.invalidateQueries({ queryKey: ['webhook-leads', 'sources'] });
    },
  });

  const addMapping = useMutation({
    mutationFn: () =>
      apiPost<PayloadMapping>(`${BASE}/sources/${selectedId}/mappings/`, {
        target_field: mapField,
        source_path: mapPath.trim(),
        transform: mapTransform || null,
        required: mapRequired,
      }),
    onSuccess: () => {
      setMapPath('');
      setMapRequired(false);
      qc.invalidateQueries({
        queryKey: ['webhook-leads', 'mappings', selectedId],
      });
    },
    onError: (e: unknown) =>
      addToast({
        type: 'error',
        title: t('webhook_leads.mapping_failed', {
          defaultValue: 'Mapping save failed',
        }),
        message: e instanceof Error ? e.message : String(e),
      }),
  });

  const deleteMapping = useMutation({
    mutationFn: (id: string) => apiDelete(`${BASE}/mappings/${id}`),
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ['webhook-leads', 'mappings', selectedId],
      }),
  });

  const sources = sourcesQ.data ?? [];
  const selected = useMemo(
    () => sources.find((s) => s.id === selectedId) ?? null,
    [sources, selectedId],
  );

  const copy = (text: string) => {
    void copyToClipboard(text);
    addToast({
      type: 'info',
      title: t('webhook_leads.copied', { defaultValue: 'Copied to clipboard' }),
    });
  };

  const statusBadge = (
    s: WebhookLog['status'],
  ): 'success' | 'warning' | 'error' =>
    s === 'accepted' ? 'success' : s === 'error' ? 'warning' : 'error';

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">
          {t('webhook_leads.title', { defaultValue: 'Webhook Leads' })}
        </h2>
        <p className="text-sm text-content-tertiary mt-1">
          {t('webhook_leads.subtitle', {
            defaultValue:
              'Secure incoming webhook endpoints that auto-create CRM leads from external sources.',
          })}
        </p>
      </div>

      {/* Reveal-once secret banner */}
      {revealedSecret && (
        <Card className="p-4 border-semantic-warning/60 bg-semantic-warning-bg">
          <div className="flex items-start gap-3">
            <KeyRound className="w-5 h-5 text-semantic-warning mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="font-medium text-semantic-warning">
                {t('webhook_leads.secret_once', {
                  defaultValue:
                    'Copy this secret now - it is shown only once and cannot be retrieved later.',
                })}
              </p>
              <div className="mt-2 space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <code className="bg-surface-primary px-2 py-1 rounded border break-all flex-1">
                    {revealedSecret.secret}
                  </code>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => copy(revealedSecret.secret)}
                  >
                    <Copy className="w-4 h-4" />
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  <code className="bg-surface-primary px-2 py-1 rounded border break-all flex-1">
                    {revealedSecret.url}
                  </code>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => copy(revealedSecret.url)}
                  >
                    <Copy className="w-4 h-4" />
                  </Button>
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                className="mt-2"
                onClick={() => setRevealedSecret(null)}
              >
                {t('webhook_leads.dismiss', { defaultValue: 'Dismiss' })}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Create source */}
      <Card className="p-4">
        <h3 className="font-medium mb-3 flex items-center gap-2">
          <Plus className="w-4 h-4" />
          {t('webhook_leads.new_source', { defaultValue: 'New webhook source' })}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <Input
            placeholder={t('webhook_leads.name', { defaultValue: 'Name' })}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <Input
            placeholder={t('webhook_leads.slug', {
              defaultValue: 'Slug (a-z0-9-_)',
            })}
            value={newSlug}
            onChange={(e) => setNewSlug(e.target.value)}
          />
          <select
            className="border rounded-md px-3 py-2 text-sm bg-surface-primary"
            value={newAuth}
            onChange={(e) =>
              setNewAuth(e.target.value as 'api_key' | 'hmac' | 'jwt')
            }
          >
            <option value="api_key">
              {t('webhook_leads.auth_api_key', { defaultValue: 'API Key' })}
            </option>
            {/* HMAC-SHA256 and JWT are protocol identifiers, shown verbatim. */}
            <option value="hmac">HMAC-SHA256</option>
            <option value="jwt">JWT</option>
          </select>
          <Input
            placeholder={t('webhook_leads.ips', {
              defaultValue: 'IP allowlist (comma-sep, optional)',
            })}
            value={newIps}
            onChange={(e) => setNewIps(e.target.value)}
          />
          <Input
            type="number"
            placeholder={t('webhook_leads.rate', {
              defaultValue: 'Rate / min',
            })}
            value={newRate}
            onChange={(e) => setNewRate(Number(e.target.value) || 60)}
          />
          <Button
            onClick={() => createSource.mutate()}
            disabled={
              !newName.trim() || !newSlug.trim() || createSource.isPending
            }
          >
            {t('webhook_leads.create', { defaultValue: 'Create source' })}
          </Button>
        </div>
      </Card>

      {/* Sources list */}
      <Card className="p-4">
        <h3 className="font-medium mb-3">
          {t('webhook_leads.sources', { defaultValue: 'Sources' })}
        </h3>
        {sources.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('webhook_leads.no_sources', {
              defaultValue: 'No webhook sources configured yet.',
            })}
          </p>
        ) : (
          <div className="space-y-2">
            {sources.map((s) => (
              <div
                key={s.id}
                className={`flex items-center gap-3 p-3 rounded-md border cursor-pointer ${
                  selectedId === s.id
                    ? 'border-oe-blue bg-oe-blue-subtle'
                    : 'border-border'
                }`}
                onClick={() => setSelectedId(s.id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="font-medium">{s.name}</div>
                  <div className="text-xs text-content-tertiary truncate">
                    /api/v1/webhook-leads/incoming/{s.slug}/ · {s.auth_method} ·{' '}
                    {s.rate_limit_per_min}/min
                  </div>
                </div>
                <Badge variant={s.is_active ? 'success' : 'neutral'}>
                  {s.is_active
                    ? t('webhook_leads.active', { defaultValue: 'Active' })
                    : t('webhook_leads.disabled', { defaultValue: 'Disabled' })}
                </Badge>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleActive.mutate(s);
                  }}
                >
                  {s.is_active
                    ? t('webhook_leads.disable', { defaultValue: 'Disable' })
                    : t('webhook_leads.enable', { defaultValue: 'Enable' })}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    rotateSecret.mutate(s.id);
                  }}
                  title={t('webhook_leads.rotate', {
                    defaultValue: 'Rotate secret',
                  })}
                >
                  <RefreshCw className="w-4 h-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async (e) => {
                    e.stopPropagation();
                    const ok = await confirm({
                      title: t('webhook_leads.confirm_delete_title', {
                        defaultValue: 'Delete webhook source?',
                      }),
                      message: t('webhook_leads.confirm_delete', {
                        defaultValue: 'Delete this webhook source?',
                      }),
                      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
                      variant: 'danger',
                    });
                    if (!ok) return;
                    deleteSource.mutate(s.id);
                  }}
                >
                  <Trash2 className="w-4 h-4 text-semantic-error" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Mappings + Logs for the selected source */}
      {selected && (
        <>
          <Card className="p-4">
            <h3 className="font-medium mb-3 flex items-center gap-2">
              <ListChecks className="w-4 h-4" />
              {t('webhook_leads.mappings_for', {
                defaultValue: 'Payload mappings',
              })}{' '}
              — {selected.name}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-2 mb-3">
              <select
                className="border rounded-md px-3 py-2 text-sm bg-surface-primary"
                value={mapField}
                onChange={(e) => setMapField(e.target.value)}
              >
                {TARGET_FIELDS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
              <Input
                placeholder={t('webhook_leads.json_path', {
                  defaultValue: 'JSON path e.g. data.email',
                })}
                value={mapPath}
                onChange={(e) => setMapPath(e.target.value)}
              />
              <select
                className="border rounded-md px-3 py-2 text-sm bg-surface-primary"
                value={mapTransform}
                onChange={(e) => setMapTransform(e.target.value)}
              >
                {TRANSFORMS.map((tr) => (
                  <option key={tr} value={tr}>
                    {tr ||
                      t('webhook_leads.no_transform', {
                        defaultValue: '(no transform)',
                      })}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={mapRequired}
                  onChange={(e) => setMapRequired(e.target.checked)}
                />
                {t('webhook_leads.required', { defaultValue: 'Required' })}
              </label>
              <Button
                size="sm"
                onClick={() => addMapping.mutate()}
                disabled={!mapPath.trim() || addMapping.isPending}
              >
                {t('webhook_leads.add_mapping', { defaultValue: 'Add' })}
              </Button>
            </div>
            <div className="space-y-1">
              {(mappingsQ.data ?? []).map((m) => (
                <div
                  key={m.id}
                  className="flex items-center gap-2 text-sm p-2 rounded border border-border-light"
                >
                  <code className="bg-surface-secondary px-2 py-0.5 rounded">
                    {m.source_path}
                  </code>
                  <span className="text-content-tertiary">→</span>
                  <span className="font-medium">{m.target_field}</span>
                  {m.transform && (
                    <Badge variant="neutral">{m.transform}</Badge>
                  )}
                  {m.required && (
                    <Badge variant="warning">
                      {t('webhook_leads.required', {
                        defaultValue: 'Required',
                      })}
                    </Badge>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto"
                    onClick={() => deleteMapping.mutate(m.id)}
                  >
                    <Trash2 className="w-3.5 h-3.5 text-semantic-error" />
                  </Button>
                </div>
              ))}
              {(mappingsQ.data ?? []).length === 0 && (
                <p className="text-sm text-content-tertiary">
                  {t('webhook_leads.no_mappings', {
                    defaultValue: 'No mappings - add at least one required rule.',
                  })}
                </p>
              )}
            </div>
          </Card>

          <Card className="p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium flex items-center gap-2">
                <ScrollText className="w-4 h-4" />
                {t('webhook_leads.logs', {
                  defaultValue: 'Recent ingestion log',
                })}
              </h3>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => logsQ.refetch()}
              >
                <RefreshCw className="w-4 h-4" />
              </Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-content-tertiary border-b">
                    <th className="py-2 pr-3">
                      {t('webhook_leads.col_time', { defaultValue: 'Time' })}
                    </th>
                    <th className="py-2 pr-3">
                      {t('webhook_leads.col_status', {
                        defaultValue: 'Status',
                      })}
                    </th>
                    <th className="py-2 pr-3">HTTP</th>
                    <th className="py-2 pr-3">
                      {t('webhook_leads.col_ip', { defaultValue: 'Remote IP' })}
                    </th>
                    <th className="py-2 pr-3">
                      {t('webhook_leads.col_detail', {
                        defaultValue: 'Lead / Error',
                      })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(logsQ.data ?? []).map((l) => (
                    <tr key={l.id} className="border-b border-border-light">
                      <td className="py-2 pr-3 whitespace-nowrap text-content-tertiary">
                        {l.received_at?.slice(0, 19).replace('T', ' ') ??
                          l.created_at.slice(0, 19).replace('T', ' ')}
                      </td>
                      <td className="py-2 pr-3">
                        <Badge variant={statusBadge(l.status)}>
                          {l.status}
                        </Badge>
                      </td>
                      <td className="py-2 pr-3">{l.http_status}</td>
                      <td className="py-2 pr-3">{l.remote_ip}</td>
                      <td className="py-2 pr-3 max-w-xs truncate">
                        {l.created_lead_id ? (
                          <span className="text-semantic-success">
                            {l.created_lead_id.slice(0, 8)}…
                          </span>
                        ) : (
                          <span className="text-semantic-error">
                            {l.error_message}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {(logsQ.data ?? []).length === 0 && (
                    <tr>
                      <td
                        colSpan={5}
                        className="py-4 text-center text-content-tertiary"
                      >
                        {t('webhook_leads.no_logs', {
                          defaultValue: 'No ingestion attempts yet.',
                        })}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

export default WebhookLeads;
