// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plug,
  Plus,
  Loader2,
  Play,
  Eye,
  Pencil,
  Trash2,
  History,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ShieldCheck,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, Card, Badge, EmptyState, SkeletonTable, RecoveryCard, ConfirmDialog } from '@/shared/ui';
import { WideModal, WideModalSection, WideModalField } from '@/shared/ui/WideModal';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fmtList } from '@/shared/lib/formatters';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface ConnectorField {
  key: string;
  label: string;
  kind: string; // text | textarea | select | secret | bool
  options: string[];
  help: string;
  secret: boolean;
}

interface ConnectorTypeInfo {
  connector_type: string;
  display_name: string;
  supported_directions: string[];
  fields: ConnectorField[];
}

interface ConnectorConfig {
  id: string;
  project_id: string | null;
  name: string;
  connector_type: string;
  direction: string;
  is_active: boolean;
  auto_push: boolean;
  auto_push_events: string[];
  settings: Record<string, unknown>;
  has_credentials: boolean;
  last_sync_at: string | null;
  last_sync_status: string | null;
  created_at: string;
  updated_at: string;
}

interface SyncLog {
  id: string;
  connector_config_id: string;
  direction: string;
  trigger: string;
  triggered_by_event: string | null;
  status: string;
  is_dry_run: boolean;
  records_in: number;
  records_out: number;
  file_keys: string[];
  warnings: string[];
  errors: string[];
  details: Record<string, unknown>;
  started_at: string;
  finished_at: string | null;
  created_at: string;
}

const AUTO_PUSH_EVENTS = ['invoice.paid', 'invoice.approved'] as const;

const STATUS_COLORS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  success: 'success',
  partial: 'warning',
  failed: 'error',
  running: 'blue',
};

// The sync-run badges printed the raw run status (`partial`) to every reader.
const STATUS_LABELS: Record<string, string> = {
  success: 'Succeeded',
  partial: 'Partial',
  failed: 'Failed',
  running: 'Running',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── Tab ───────────────────────────────────────────────────────────────── */

export function ConnectorsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<ConnectorConfig | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<Record<string, SyncLog>>({});

  const typesQuery = useQuery({
    queryKey: ['finance', 'connector-types'],
    queryFn: () => apiGet<ConnectorTypeInfo[]>('/v1/finance/connectors/types/'),
  });

  const configsQuery = useQuery({
    queryKey: ['finance', 'connectors', projectId],
    queryFn: () =>
      apiGet<{ items: ConnectorConfig[]; total: number }>(
        `/v1/finance/connectors/?project_id=${encodeURIComponent(projectId)}`,
      ),
  });

  const configs = configsQuery.data?.items ?? [];
  const types = typesQuery.data ?? [];

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['finance', 'connectors', projectId] });

  const validateMut = useMutation({
    mutationFn: (id: string) =>
      apiPost<{ ok: boolean; problems: string[] }>(`/v1/finance/connectors/${id}/validate/`),
    onSuccess: (res) => {
      if (res.ok) {
        addToast({
          type: 'success',
          title: t('finance.connectors.valid', { defaultValue: 'Configuration looks good' }),
        });
      } else {
        addToast({
          type: 'warning',
          title: t('finance.connectors.invalid', { defaultValue: 'Configuration needs attention' }),
          message: res.problems.join(' '),
        });
      }
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const syncMut = useMutation({
    mutationFn: ({ id, dryRun }: { id: string; dryRun: boolean }) =>
      apiPost<SyncLog>(`/v1/finance/connectors/${id}/sync/`, { direction: 'both', dry_run: dryRun }),
    onSuccess: (log, vars) => {
      setLastResult((prev) => ({ ...prev, [vars.id]: log }));
      setExpanded(vars.id);
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['finance', 'connector-logs', vars.id] });
      const tone = log.status === 'success' ? 'success' : log.status === 'failed' ? 'error' : 'warning';
      addToast({
        type: tone,
        title: vars.dryRun
          ? t('finance.connectors.dry_run_done', { defaultValue: 'Dry run complete' })
          : t('finance.connectors.sync_done', { defaultValue: 'Sync complete' }),
        message: t('finance.connectors.sync_counts', {
          defaultValue: '{{out}} sent, {{in}} read',
          out: log.records_out,
          in: log.records_in,
        }),
      });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/finance/connectors/${id}/`),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('finance.connectors.deleted', { defaultValue: 'Connector deleted' }),
      });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const handleDelete = async (c: ConnectorConfig) => {
    const ok = await confirm({
      title: t('finance.connectors.confirm_delete_title', { defaultValue: 'Delete this connector?' }),
      message: t('finance.connectors.confirm_delete_msg', {
        defaultValue: 'The connector and its sync history will be permanently removed. This cannot be undone.',
      }),
      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (ok) deleteMut.mutate(c.id);
  };

  const handleRunSync = async (c: ConnectorConfig) => {
    const ok = await confirm({
      title: t('finance.connectors.confirm_sync_title', { defaultValue: 'Run a live sync?' }),
      message: t('finance.connectors.confirm_sync_msg', {
        defaultValue:
          'This writes export files and may post ledger entries from the inbound file. Run a dry run first if you want to preview.',
      }),
      confirmLabel: t('finance.connectors.run_sync', { defaultValue: 'Run sync' }),
    });
    if (ok) syncMut.mutate({ id: c.id, dryRun: false });
  };

  if (configsQuery.isLoading) return <SkeletonTable rows={4} columns={4} />;
  if (configsQuery.isError) {
    return <RecoveryCard error={configsQuery.error} onRetry={() => configsQuery.refetch()} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-content-secondary max-w-2xl">
          {t('finance.connectors.intro', {
            defaultValue:
              'Connect to your accounting or ERP system. Push invoices and payments out as files, and import a general-ledger file back in as balanced ledger entries. Run a dry run to preview before anything is written.',
          })}
        </p>
        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={() => {
            setEditing(null);
            setShowModal(true);
          }}
        >
          {t('finance.connectors.new', { defaultValue: 'New connector' })}
        </Button>
      </div>

      {configs.length === 0 ? (
        <EmptyState
          icon={<Plug size={28} strokeWidth={1.5} />}
          title={t('finance.connectors.empty_title', { defaultValue: 'No connectors yet' })}
          description={t('finance.connectors.empty_desc', {
            defaultValue:
              'Add a file connector to export this project’s invoices and payments, or to import general-ledger entries from your accounting package.',
          })}
          action={{
            label: t('finance.connectors.new', { defaultValue: 'New connector' }),
            onClick: () => {
              setEditing(null);
              setShowModal(true);
            },
          }}
        />
      ) : (
        <div className="space-y-3">
          {configs.map((c) => {
            const typeInfo = types.find((tp) => tp.connector_type === c.connector_type);
            const result = lastResult[c.id];
            return (
              <Card key={c.id} padding="none" className="overflow-hidden">
                <div className="p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-content-primary truncate">{c.name}</span>
                        <Badge variant={c.is_active ? 'success' : 'neutral'}>
                          {c.is_active
                            ? t('finance.connectors.active', { defaultValue: 'Active' })
                            : t('finance.connectors.inactive', { defaultValue: 'Inactive' })}
                        </Badge>
                        {c.has_credentials && (
                          <span
                            className="inline-flex items-center gap-1 text-2xs text-content-tertiary"
                            title={t('finance.connectors.credentials_set', { defaultValue: 'Credentials are set' })}
                          >
                            <ShieldCheck size={12} /> {t('finance.connectors.secured', { defaultValue: 'Secured' })}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-tertiary">
                        <span>{typeInfo?.display_name ?? c.connector_type}</span>
                        <span className="capitalize">{c.direction}</span>
                        {c.auto_push && c.auto_push_events.length > 0 && (
                          <span>
                            {t('finance.connectors.auto_on', {
                              defaultValue: 'Auto-push on {{events}}',
                              events: fmtList(c.auto_push_events),
                            })}
                          </span>
                        )}
                        {c.last_sync_at && (
                          <span className="inline-flex items-center gap-1">
                            {t('finance.connectors.last_sync', { defaultValue: 'Last sync' })}:{' '}
                            <DateDisplay value={c.last_sync_at} />
                            {c.last_sync_status && (
                              <Badge variant={STATUS_COLORS[c.last_sync_status] ?? 'neutral'}>
                                {c.last_sync_status}
                              </Badge>
                            )}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<CheckCircle2 size={14} />}
                        onClick={() => validateMut.mutate(c.id)}
                        loading={validateMut.isPending && validateMut.variables === c.id}
                      >
                        {t('finance.connectors.validate', { defaultValue: 'Validate' })}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<Eye size={14} />}
                        onClick={() => syncMut.mutate({ id: c.id, dryRun: true })}
                        loading={
                          syncMut.isPending && syncMut.variables?.id === c.id && syncMut.variables?.dryRun === true
                        }
                      >
                        {t('finance.connectors.dry_run', { defaultValue: 'Dry run' })}
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<Play size={14} />}
                        onClick={() => handleRunSync(c)}
                        loading={
                          syncMut.isPending && syncMut.variables?.id === c.id && syncMut.variables?.dryRun === false
                        }
                      >
                        {t('finance.connectors.run_sync', { defaultValue: 'Run sync' })}
                      </Button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(c);
                          setShowModal(true);
                        }}
                        title={t('common.edit', { defaultValue: 'Edit' })}
                        aria-label={t('common.edit', { defaultValue: 'Edit' })}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setExpanded(expanded === c.id ? null : c.id)}
                        title={t('finance.connectors.history', { defaultValue: 'Sync history' })}
                        aria-label={t('finance.connectors.history', { defaultValue: 'Sync history' })}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                      >
                        <History size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(c)}
                        title={t('common.delete', { defaultValue: 'Delete' })}
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-red-50 hover:text-red-600 transition-colors dark:hover:bg-red-950/30"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>

                  {/* Inline result of the most recent run this session */}
                  {result && <SyncResultPanel log={result} />}
                </div>

                {expanded === c.id && <SyncHistory configId={c.id} />}
              </Card>
            );
          })}
        </div>
      )}

      {showModal && (
        <ConnectorModal
          projectId={projectId}
          types={types}
          editing={editing}
          onClose={() => {
            setShowModal(false);
            setEditing(null);
          }}
          onSaved={() => {
            setShowModal(false);
            setEditing(null);
            invalidate();
          }}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Sync result panel ─────────────────────────────────────────────────── */

function SyncResultPanel({ log }: { log: SyncLog }) {
  const { t } = useTranslation();
  const icon =
    log.status === 'success' ? (
      <CheckCircle2 size={14} className="text-semantic-success" />
    ) : log.status === 'failed' ? (
      <XCircle size={14} className="text-semantic-error" />
    ) : (
      <AlertTriangle size={14} className="text-amber-500" />
    );
  return (
    <div className="mt-3 rounded-lg border border-border-light bg-surface-secondary/40 p-3 text-xs">
      <div className="flex items-center gap-2 font-medium text-content-primary">
        {icon}
        <span>
          {log.is_dry_run
            ? t('finance.connectors.dry_run_result', { defaultValue: 'Dry run preview' })
            : t('finance.connectors.sync_result', { defaultValue: 'Sync result' })}
        </span>
        <Badge variant={STATUS_COLORS[log.status] ?? 'neutral'}>
          {t(`finance.connectors.log_status_${log.status}`, { defaultValue: STATUS_LABELS[log.status] ?? log.status })}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-content-secondary">
        <span>
          {t('finance.connectors.records_out', { defaultValue: 'Sent' })}: <b>{log.records_out}</b>
        </span>
        <span>
          {t('finance.connectors.records_in', { defaultValue: 'Read' })}: <b>{log.records_in}</b>
        </span>
        {log.file_keys.length > 0 && (
          <span>
            {t('finance.connectors.files', { defaultValue: 'Files' })}: <b>{log.file_keys.length}</b>
          </span>
        )}
      </div>
      {log.file_keys.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-content-tertiary">
          {log.file_keys.map((k) => (
            <li key={k} className="font-mono text-2xs break-all">
              {k}
            </li>
          ))}
        </ul>
      )}
      {log.warnings.map((w, i) => (
        <p key={`w${i}`} className="mt-1 text-amber-600 dark:text-amber-400">
          {w}
        </p>
      ))}
      {log.errors.map((e, i) => (
        <p key={`e${i}`} className="mt-1 text-red-600 dark:text-red-400">
          {e}
        </p>
      ))}
    </div>
  );
}

/* ── Sync history ──────────────────────────────────────────────────────── */

function SyncHistory({ configId }: { configId: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['finance', 'connector-logs', configId],
    queryFn: () =>
      apiGet<{ items: SyncLog[]; total: number }>(`/v1/finance/connectors/${configId}/logs/?limit=20`),
  });

  if (isLoading) {
    return (
      <div className="border-t border-border-light p-4 text-xs text-content-tertiary">
        <Loader2 size={14} className="inline animate-spin mr-1.5" />
        {t('common.loading', { defaultValue: 'Loading...' })}
      </div>
    );
  }

  const logs = data?.items ?? [];
  if (logs.length === 0) {
    return (
      <div className="border-t border-border-light p-4 text-xs text-content-tertiary">
        {t('finance.connectors.no_history', { defaultValue: 'No sync runs yet.' })}
      </div>
    );
  }

  return (
    <div className="border-t border-border-light overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-surface-secondary/50 text-content-tertiary">
            <th className="px-4 py-2 text-left font-medium">{t('finance.connectors.col_when', { defaultValue: 'When' })}</th>
            <th className="px-4 py-2 text-left font-medium">{t('finance.connectors.col_direction', { defaultValue: 'Direction' })}</th>
            <th className="px-4 py-2 text-left font-medium">{t('finance.connectors.col_trigger', { defaultValue: 'Trigger' })}</th>
            <th className="px-4 py-2 text-left font-medium">{t('finance.connectors.col_status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2 text-right font-medium">{t('finance.connectors.records_out', { defaultValue: 'Sent' })}</th>
            <th className="px-4 py-2 text-right font-medium">{t('finance.connectors.records_in', { defaultValue: 'Read' })}</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((log) => (
            <tr key={log.id} className="border-t border-border-light">
              <td className="px-4 py-2 text-content-secondary">
                <DateDisplay value={log.started_at} format="datetime" />
              </td>
              <td className="px-4 py-2 capitalize text-content-secondary">{log.direction}</td>
              <td className="px-4 py-2 text-content-tertiary">
                {log.is_dry_run ? t('finance.connectors.dry', { defaultValue: 'dry run' }) : log.trigger}
              </td>
              <td className="px-4 py-2">
                <Badge variant={STATUS_COLORS[log.status] ?? 'neutral'}>
                  {t(`finance.connectors.log_status_${log.status}`, {
                    defaultValue: STATUS_LABELS[log.status] ?? log.status,
                  })}
                </Badge>
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{log.records_out}</td>
              <td className="px-4 py-2 text-right tabular-nums">{log.records_in}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Create / Edit modal ───────────────────────────────────────────────── */

/**
 * Stringified settings seed for the connector form. Also serves as the
 * baseline an edit diffs against, so the two cannot drift apart.
 */
function settingsFromConnector(editing: ConnectorConfig | null): Record<string, string> {
  const out: Record<string, string> = {};
  const src = editing?.settings ?? {};
  for (const [k, v] of Object.entries(src)) {
    if (typeof v === 'string') out[k] = v;
    else if (v != null) out[k] = String(v);
  }
  if (!('format' in out)) out.format = 'csv';
  return out;
}

function ConnectorModal({
  projectId,
  types,
  editing,
  onClose,
  onSaved,
}: {
  projectId: string;
  types: ConnectorTypeInfo[];
  editing: ConnectorConfig | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = editing !== null;

  const [name, setName] = useState(editing?.name ?? '');
  const [connectorType, setConnectorType] = useState(
    editing?.connector_type ?? types[0]?.connector_type ?? 'file_csv',
  );
  const [direction, setDirection] = useState(editing?.direction ?? 'both');
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [autoPush, setAutoPush] = useState(editing?.auto_push ?? false);
  const [autoPushEvents, setAutoPushEvents] = useState<string[]>(editing?.auto_push_events ?? []);
  const [settings, setSettings] = useState<Record<string, string>>(() =>
    settingsFromConnector(editing),
  );
  const [secrets, setSecrets] = useState<Record<string, string>>({});

  const typeInfo = useMemo(
    () => types.find((tp) => tp.connector_type === connectorType),
    [types, connectorType],
  );
  const nonSecretFields = (typeInfo?.fields ?? []).filter((f) => !f.secret);
  const secretFields = (typeInfo?.fields ?? []).filter((f) => f.secret);

  const saveMut = useMutation({
    mutationFn: () => {
      const credentials =
        Object.keys(secrets).length > 0
          ? Object.fromEntries(Object.entries(secrets).filter(([, v]) => v.trim() !== ''))
          : undefined;
      const body = {
        direction,
        is_active: isActive,
        auto_push: autoPush,
        auto_push_events: autoPushEvents,
        settings,
        ...(credentials && Object.keys(credentials).length > 0 ? { credentials } : {}),
      };
      if (isEdit && editing) {
        // Only what the user actually changed. Toggling a connector off used
        // to resend its whole settings blob and event list as this tab had
        // loaded them, so an endpoint someone else had just corrected was
        // silently rolled back. The route dumps with `exclude_unset=True`, so
        // an omitted field is left alone. The array and the settings blob are
        // compared by content because a fresh object is built on every render.
        const patch: Record<string, unknown> = {};
        if (direction !== (editing.direction ?? 'both')) patch.direction = direction;
        if (isActive !== (editing.is_active ?? true)) patch.is_active = isActive;
        if (autoPush !== (editing.auto_push ?? false)) patch.auto_push = autoPush;
        if (JSON.stringify(autoPushEvents) !== JSON.stringify(editing.auto_push_events ?? [])) {
          patch.auto_push_events = autoPushEvents;
        }
        if (JSON.stringify(settings) !== JSON.stringify(settingsFromConnector(editing))) {
          patch.settings = settings;
        }
        if (credentials && Object.keys(credentials).length > 0) patch.credentials = credentials;
        return apiPatch(`/v1/finance/connectors/${editing.id}/`, patch);
      }
      return apiPost('/v1/finance/connectors/', {
        ...body,
        project_id: projectId,
        name,
        connector_type: connectorType,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: isEdit
          ? t('finance.connectors.updated', { defaultValue: 'Connector updated' })
          : t('finance.connectors.created', { defaultValue: 'Connector created' }),
      });
      onSaved();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const canSave = name.trim().length > 0 && connectorType.length > 0;

  const toggleEvent = (ev: string) => {
    setAutoPushEvents((prev) => (prev.includes(ev) ? prev.filter((x) => x !== ev) : [...prev, ev]));
  };

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      busy={saveMut.isPending}
      title={
        isEdit
          ? t('finance.connectors.edit_title', { defaultValue: 'Edit connector' })
          : t('finance.connectors.new_title', { defaultValue: 'New connector' })
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saveMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMut.mutate()}
            disabled={!canSave || saveMut.isPending}
            loading={saveMut.isPending}
          >
            {isEdit ? t('common.save', { defaultValue: 'Save Changes' }) : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('finance.connectors.field_name', { defaultValue: 'Name' })} required>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputCls}
            placeholder={t('finance.connectors.name_placeholder', { defaultValue: 'e.g. DATEV export' })}
          />
        </WideModalField>

        <WideModalField label={t('finance.connectors.field_type', { defaultValue: 'Type' })} required>
          <select
            value={connectorType}
            onChange={(e) => setConnectorType(e.target.value)}
            className={inputCls}
            disabled={isEdit}
          >
            {types.map((tp) => (
              <option key={tp.connector_type} value={tp.connector_type}>
                {tp.display_name}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField label={t('finance.connectors.field_direction', { defaultValue: 'Direction' })}>
          <select value={direction} onChange={(e) => setDirection(e.target.value)} className={inputCls}>
            <option value="both">{t('finance.connectors.dir_both', { defaultValue: 'Push and pull' })}</option>
            <option value="push">{t('finance.connectors.dir_push', { defaultValue: 'Push only (export)' })}</option>
            <option value="pull">{t('finance.connectors.dir_pull', { defaultValue: 'Pull only (import ledger)' })}</option>
          </select>
        </WideModalField>

        <WideModalField label={t('finance.connectors.field_active', { defaultValue: 'Status' })}>
          <label className="flex h-10 items-center gap-2 text-sm text-content-secondary">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            {t('finance.connectors.active', { defaultValue: 'Active' })}
          </label>
        </WideModalField>

        {/* Connector-type settings (generic form builder) */}
        {nonSecretFields.map((f) => (
          <WideModalField key={f.key} label={f.label} hint={f.help || undefined}>
            {f.kind === 'select' ? (
              <select
                value={settings[f.key] ?? f.options[0] ?? ''}
                onChange={(e) => setSettings((p) => ({ ...p, [f.key]: e.target.value }))}
                className={inputCls}
              >
                {f.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : f.kind === 'textarea' ? (
              <textarea
                value={settings[f.key] ?? ''}
                onChange={(e) => setSettings((p) => ({ ...p, [f.key]: e.target.value }))}
                rows={2}
                className={clsx(inputCls, 'h-auto py-2 resize-none')}
              />
            ) : (
              <input
                value={settings[f.key] ?? ''}
                onChange={(e) => setSettings((p) => ({ ...p, [f.key]: e.target.value }))}
                className={inputCls}
              />
            )}
          </WideModalField>
        ))}

        {/* Secret fields (write-only). Never prefilled; placeholder hints when set. */}
        {secretFields.map((f) => (
          <WideModalField key={f.key} label={f.label} hint={f.help || undefined}>
            <input
              type="password"
              value={secrets[f.key] ?? ''}
              onChange={(e) => setSecrets((p) => ({ ...p, [f.key]: e.target.value }))}
              className={inputCls}
              placeholder={
                editing?.has_credentials
                  ? t('finance.connectors.secret_set', { defaultValue: 'Set - leave blank to keep' })
                  : ''
              }
              autoComplete="new-password"
            />
          </WideModalField>
        ))}

        {/* Auto-push */}
        <WideModalField label={t('finance.connectors.field_auto', { defaultValue: 'Automation' })} span={2}>
          <label className="flex items-center gap-2 text-sm text-content-secondary">
            <input type="checkbox" checked={autoPush} onChange={(e) => setAutoPush(e.target.checked)} />
            {t('finance.connectors.auto_push', { defaultValue: 'Push automatically when these events happen' })}
          </label>
          {autoPush && (
            <div className="mt-2 flex flex-wrap gap-2">
              {AUTO_PUSH_EVENTS.map((ev) => (
                <button
                  key={ev}
                  type="button"
                  onClick={() => toggleEvent(ev)}
                  className={clsx(
                    'rounded-full px-3 py-1 text-xs font-medium border transition-all',
                    autoPushEvents.includes(ev)
                      ? 'bg-oe-blue text-white border-oe-blue'
                      : 'border-border text-content-secondary hover:border-oe-blue/40',
                  )}
                >
                  {ev}
                </button>
              ))}
            </div>
          )}
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
