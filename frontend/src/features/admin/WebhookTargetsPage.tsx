/**
 * WebhookTargetsPage — Epic B / B11 admin UI for notification webhooks.
 *
 * One row per registered `WebhookTarget`.  Admin actions:
 *
 *   • Create a new target  (POST /api/v1/notifications/webhooks/)
 *   • Toggle active        (PATCH …/{id}/ { active })
 *   • Delete a target      (DELETE …/{id}/)
 *
 * The secret is never exposed back to the client — the row shows
 * "Secret set" / "No secret" only.  Failure counters live on the row
 * so a broken endpoint is visible without reading server logs.
 *
 * Mounted at `/admin/webhook-targets` for admins; non-admin sessions
 * hit the same 403 the backend returns.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Loader2, Plus, Power, Trash2, Webhook } from 'lucide-react';
import { apiDelete, apiGet, apiPost, apiPatch } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

interface WebhookTarget {
  id: string;
  name: string;
  url: string;
  event_filter: string;
  has_secret: boolean;
  active: boolean;
  last_status: number | null;
  last_attempt_at: string | null;
  failure_count: number;
  created_at: string;
  updated_at: string;
}

interface CreatePayload {
  name: string;
  url: string;
  event_filter: string;
  secret: string | null;
  active: boolean;
}

const QUERY_KEY = ['admin-webhook-targets'];

export function WebhookTargetsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);

  const { data: targets, isLoading, isError } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => apiGet<WebhookTarget[]>('/v1/notifications/webhooks/'),
    retry: false,
  });

  const createMutation = useMutation({
    mutationFn: (payload: CreatePayload) =>
      apiPost<WebhookTarget>('/v1/notifications/webhooks/', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setShowCreate(false);
      addToast({
        type: 'success',
        title: t('webhook_targets.created', { defaultValue: 'Webhook created' }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('webhook_targets.create_failed', { defaultValue: 'Create failed' }),
        message: err.message,
      });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      apiPatch<WebhookTarget>(`/v1/notifications/webhooks/${id}/`, { active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      apiDelete(`/v1/notifications/webhooks/${id}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      addToast({
        type: 'success',
        title: t('webhook_targets.deleted', { defaultValue: 'Webhook deleted' }),
      });
    },
  });

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 space-y-6" data-testid="webhook-targets-page">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-content-primary flex items-center gap-2">
            <Webhook size={20} className="text-oe-blue" />
            {t('webhook_targets.title', { defaultValue: 'Notification Webhooks' })}
          </h1>
          <p className="text-sm text-content-secondary mt-1">
            {t('webhook_targets.subtitle', {
              defaultValue:
                'Outbound HTTP endpoints that receive matching notification events.',
            })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-2 text-xs font-semibold text-white hover:bg-oe-blue/90"
        >
          <Plus size={14} />
          {t('webhook_targets.new', { defaultValue: 'New webhook' })}
        </button>
      </header>

      {showCreate && (
        <CreateForm
          onSubmit={(payload) => createMutation.mutate(payload)}
          onCancel={() => setShowCreate(false)}
          isPending={createMutation.isPending}
        />
      )}

      <section className="rounded-xl border border-border-light bg-surface-elevated overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-sm text-content-secondary">
            <Loader2 size={16} className="inline-block animate-spin mr-2" />
            {t('common.loading', { defaultValue: 'Loading…' })}
          </div>
        ) : isError ? (
          <div className="p-8 text-center text-sm text-semantic-error">
            {t('webhook_targets.load_error', {
              defaultValue: 'Could not load webhook targets.',
            })}
          </div>
        ) : !targets || targets.length === 0 ? (
          <div className="p-10 text-center">
            <Webhook size={28} className="mx-auto mb-2 text-content-quaternary" />
            <p className="text-sm font-medium text-content-primary">
              {t('webhook_targets.empty_title', { defaultValue: 'No webhooks yet' })}
            </p>
            <p className="text-xs text-content-tertiary mt-1">
              {t('webhook_targets.empty_hint', {
                defaultValue:
                  'Create your first webhook to forward notification events to Slack, Jira, or any HTTP endpoint.',
              })}
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary/40 text-xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="text-left px-4 py-2">{t('common.name', { defaultValue: 'Name' })}</th>
                <th className="text-left px-4 py-2">{t('webhook_targets.url', { defaultValue: 'URL' })}</th>
                <th className="text-left px-4 py-2">{t('webhook_targets.filter', { defaultValue: 'Event filter' })}</th>
                <th className="text-left px-4 py-2">{t('webhook_targets.status', { defaultValue: 'Status' })}</th>
                <th className="text-right px-4 py-2">{t('common.actions', { defaultValue: 'Actions' })}</th>
              </tr>
            </thead>
            <tbody>
              {targets.map((target) => (
                <tr key={target.id} className="border-t border-border-light/60">
                  <td className="px-4 py-3">
                    <div className="font-medium text-content-primary">{target.name}</div>
                    <div className="text-2xs text-content-quaternary">
                      {target.has_secret
                        ? t('webhook_targets.secret_set', { defaultValue: 'Secret set' })
                        : t('webhook_targets.no_secret', { defaultValue: 'No secret' })}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-content-secondary truncate max-w-[260px]">
                    {target.url}
                  </td>
                  <td className="px-4 py-3 text-xs text-content-secondary">{target.event_filter}</td>
                  <td className="px-4 py-3 text-xs">
                    <StatusBadge target={target} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() =>
                          toggleMutation.mutate({ id: target.id, active: !target.active })
                        }
                        className="rounded-md p-1.5 text-content-tertiary hover:bg-surface-secondary"
                        title={
                          target.active
                            ? t('webhook_targets.deactivate', { defaultValue: 'Deactivate' })
                            : t('webhook_targets.activate', { defaultValue: 'Activate' })
                        }
                        aria-label={target.active ? 'deactivate' : 'activate'}
                      >
                        <Power size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => deleteMutation.mutate(target.id)}
                        className="rounded-md p-1.5 text-content-tertiary hover:bg-rose-50 hover:text-rose-500"
                        title={t('common.delete', { defaultValue: 'Delete' })}
                        aria-label="delete"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function StatusBadge({ target }: { target: WebhookTarget }) {
  const active = target.active;
  const lastOk = target.last_status != null && target.last_status >= 200 && target.last_status < 300;
  if (!active) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-2xs text-content-tertiary">
        Inactive
      </span>
    );
  }
  if (target.last_status == null) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs text-oe-blue-text">
        Active · never fired
      </span>
    );
  }
  if (lastOk) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 dark:bg-emerald-900/30 px-2 py-0.5 text-2xs text-emerald-700 dark:text-emerald-300">
        OK · {target.last_status}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 dark:bg-rose-900/30 px-2 py-0.5 text-2xs text-rose-700 dark:text-rose-300">
      Failed · {target.last_status} (×{target.failure_count})
    </span>
  );
}

function CreateForm({
  onSubmit,
  onCancel,
  isPending,
}: {
  onSubmit: (payload: CreatePayload) => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [eventFilter, setEventFilter] = useState('*');
  const [secret, setSecret] = useState('');

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          name: name.trim(),
          url: url.trim(),
          event_filter: eventFilter.trim() || '*',
          secret: secret.trim() || null,
          active: true,
        });
      }}
      className="rounded-xl border border-border-light bg-surface-elevated p-5 space-y-3"
    >
      <h2 className="text-sm font-semibold text-content-primary">
        {t('webhook_targets.new_title', { defaultValue: 'New webhook target' })}
      </h2>
      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1 text-xs text-content-secondary">
          <span>{t('common.name', { defaultValue: 'Name' })}</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            minLength={1}
            maxLength={120}
            className="w-full rounded-md border border-border-light px-2 py-1.5 text-sm"
          />
        </label>
        <label className="space-y-1 text-xs text-content-secondary">
          <span>{t('webhook_targets.filter', { defaultValue: 'Event filter' })}</span>
          <input
            type="text"
            value={eventFilter}
            onChange={(e) => setEventFilter(e.target.value)}
            placeholder="*"
            className="w-full rounded-md border border-border-light px-2 py-1.5 text-sm font-mono"
          />
        </label>
      </div>
      <label className="block space-y-1 text-xs text-content-secondary">
        <span>{t('webhook_targets.url', { defaultValue: 'URL (https://…)' })}</span>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          pattern="https?://.+"
          maxLength={2048}
          className="w-full rounded-md border border-border-light px-2 py-1.5 text-sm font-mono"
        />
      </label>
      <label className="block space-y-1 text-xs text-content-secondary">
        <span>{t('webhook_targets.secret', { defaultValue: 'HMAC secret (optional)' })}</span>
        <input
          type="text"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          maxLength={255}
          autoComplete="off"
          className="w-full rounded-md border border-border-light px-2 py-1.5 text-sm font-mono"
        />
      </label>
      <div className="flex items-center justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-border-light px-3 py-1.5 text-xs text-content-secondary hover:bg-surface-secondary"
        >
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </button>
        <button
          type="submit"
          disabled={isPending}
          className="inline-flex items-center gap-1 rounded-md bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white hover:bg-oe-blue/90 disabled:opacity-50"
        >
          {isPending && <Loader2 size={12} className="animate-spin" />}
          {t('common.create', { defaultValue: 'Create' })}
        </button>
      </div>
    </form>
  );
}

export default WebhookTargetsPage;
