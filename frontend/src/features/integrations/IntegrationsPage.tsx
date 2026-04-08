import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  MessageSquare,
  Hash,
  Send,
  Mail,
  Globe,
  Calendar,
  CheckCircle2,
  XCircle,
  Loader2,
  Plus,
  Trash2,
  TestTube2,
  X,
  type LucideIcon,
} from 'lucide-react';
import { Card, CardContent, Badge, Button, Input, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

type IntegrationType = 'teams' | 'slack' | 'telegram' | 'email' | 'webhook';

interface IntegrationConfig {
  id: string;
  user_id: string;
  project_id: string | null;
  integration_type: IntegrationType;
  name: string;
  config: Record<string, string>;
  events: string[];
  is_active: boolean;
  last_triggered_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface IntegrationConfigListResponse {
  items: IntegrationConfig[];
  total: number;
}

/* ── Connector definitions ─────────────────────────────────────────────── */

interface ConnectorDef {
  type: IntegrationType;
  nameKey: string;
  defaultName: string;
  descKey: string;
  defaultDesc: string;
  icon: LucideIcon;
  color: string;
  fields: { key: string; label: string; placeholder: string; type?: string }[];
  setupInstructions: string;
}

const CONNECTORS: ConnectorDef[] = [
  {
    type: 'teams',
    nameKey: 'integrations.teams',
    defaultName: 'Microsoft Teams',
    descKey: 'integrations.teams_desc',
    defaultDesc: 'Send notifications to your Teams channel via Incoming Webhook',
    icon: MessageSquare,
    color: 'bg-[#6264A7]',
    fields: [
      {
        key: 'webhook_url',
        label: 'Webhook URL',
        placeholder: 'https://outlook.office.com/webhook/...',
      },
    ],
    setupInstructions:
      '1. Open your Teams channel\n2. Click "..." > Connectors > Incoming Webhook\n3. Give it a name, click Create\n4. Copy the webhook URL and paste it here',
  },
  {
    type: 'slack',
    nameKey: 'integrations.slack',
    defaultName: 'Slack',
    descKey: 'integrations.slack_desc',
    defaultDesc: 'Send notifications to Slack via Incoming Webhook',
    icon: Hash,
    color: 'bg-[#4A154B]',
    fields: [
      {
        key: 'webhook_url',
        label: 'Webhook URL',
        placeholder: 'https://hooks.slack.com/services/T.../B.../...',
      },
    ],
    setupInstructions:
      '1. Go to api.slack.com/apps > Create New App\n2. Enable Incoming Webhooks\n3. Add New Webhook to Workspace\n4. Copy the webhook URL and paste it here',
  },
  {
    type: 'telegram',
    nameKey: 'integrations.telegram',
    defaultName: 'Telegram',
    descKey: 'integrations.telegram_desc',
    defaultDesc: 'Get notified via Telegram bot',
    icon: Send,
    color: 'bg-[#0088cc]',
    fields: [
      {
        key: 'bot_token',
        label: 'Bot Token',
        placeholder: '123456789:ABCdefGHIjklMNOpqrsTUVwxyz',
        type: 'password',
      },
      {
        key: 'chat_id',
        label: 'Chat ID',
        placeholder: '-1001234567890',
      },
    ],
    setupInstructions:
      '1. Message @BotFather on Telegram > /newbot\n2. Copy the bot token\n3. Add the bot to your group/channel\n4. Get your chat_id (message @userinfobot or use the Telegram API)',
  },
  {
    type: 'email',
    nameKey: 'integrations.email',
    defaultName: 'Email',
    descKey: 'integrations.email_desc',
    defaultDesc: 'Receive email notifications (SMTP)',
    icon: Mail,
    color: 'bg-blue-600',
    fields: [],
    setupInstructions: 'Email notifications will be available in a future update.',
  },
  {
    type: 'webhook',
    nameKey: 'integrations.webhook',
    defaultName: 'Webhooks',
    descKey: 'integrations.webhook_desc',
    defaultDesc: 'Send events to any URL (HTTP POST)',
    icon: Globe,
    color: 'bg-gray-600',
    fields: [],
    setupInstructions: 'Use the Webhooks tab in Settings to configure custom webhook endpoints.',
  },
  {
    type: 'email' as IntegrationType,
    nameKey: 'integrations.calendar',
    defaultName: 'Calendar',
    descKey: 'integrations.calendar_desc',
    defaultDesc: 'Subscribe in Google/Outlook Calendar (iCal feed)',
    icon: Calendar,
    color: 'bg-green-600',
    fields: [],
    setupInstructions: 'Calendar feeds are available per project. Go to Project Settings > Calendar.',
  },
];

// Only these types support the connect flow
const CONNECTABLE_TYPES: IntegrationType[] = ['teams', 'slack', 'telegram'];

/* ── API helpers ────────────────────────────────────────────────────────── */

function fetchConfigs(): Promise<IntegrationConfigListResponse> {
  return apiGet('/v1/integrations/configs');
}

/* ── Connect Modal ─────────────────────────────────────────────────────── */

function ConnectModal({
  connector,
  onClose,
  onSaved,
}: {
  connector: ConnectorDef;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState(connector.defaultName);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(connector.fields.map((f) => [f.key, '']))
  );
  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    // Validate all fields are filled
    for (const f of connector.fields) {
      if (!fieldValues[f.key]?.trim()) {
        addToast({ type: 'error', title: 'Validation', message: `${f.label} is required` });
        return;
      }
    }
    setSaving(true);
    try {
      await apiPost('/v1/integrations/configs', {
        integration_type: connector.type,
        name: name.trim() || connector.defaultName,
        config: fieldValues,
        events: ['*'],
      });
      addToast({ type: 'success', title: t('integrations.connected', 'Connected successfully') });
      onSaved();
    } catch {
      addToast({ type: 'error', title: t('integrations.connect_failed', 'Connection failed') });
    } finally {
      setSaving(false);
    }
  }, [connector, name, fieldValues, addToast, t, onSaved]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-lg rounded-xl bg-surface-primary p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`flex h-10 w-10 items-center justify-center rounded-lg text-white ${connector.color}`}>
              <connector.icon size={20} />
            </div>
            <h2 className="text-lg font-semibold text-primary">
              {t('integrations.connect_title', 'Connect {{name}}', { name: connector.defaultName })}
            </h2>
          </div>
          <button onClick={onClose} className="text-secondary hover:text-primary">
            <X size={20} />
          </button>
        </div>

        {/* Setup instructions */}
        <div className="mb-4 rounded-lg bg-surface-secondary p-3 text-sm text-secondary">
          <p className="mb-1 font-medium text-primary">
            {t('integrations.setup_steps', 'Setup instructions')}:
          </p>
          <pre className="whitespace-pre-wrap font-sans text-xs">{connector.setupInstructions}</pre>
        </div>

        {/* Name field */}
        <div className="mb-3">
          <label className="mb-1 block text-sm font-medium text-primary">
            {t('common.name', 'Name')}
          </label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={connector.defaultName} />
        </div>

        {/* Connector-specific fields */}
        {connector.fields.map((field) => (
          <div key={field.key} className="mb-3">
            <label className="mb-1 block text-sm font-medium text-primary">{field.label}</label>
            <Input
              type={field.type || 'text'}
              value={fieldValues[field.key] || ''}
              onChange={(e) => setFieldValues((prev) => ({ ...prev, [field.key]: e.target.value }))}
              placeholder={field.placeholder}
            />
          </div>
        ))}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 size={16} className="mr-1 animate-spin" />}
            {t('integrations.connect', 'Connect')}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function IntegrationsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [connectingType, setConnectingType] = useState<ConnectorDef | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['integration-configs'],
    queryFn: fetchConfigs,
  });

  const configs = data?.items ?? [];

  // Map: integration_type -> list of configs
  const configsByType = configs.reduce<Record<string, IntegrationConfig[]>>((acc, c) => {
    (acc[c.integration_type] ??= []).push(c);
    return acc;
  }, {});

  const deleteMut = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/integrations/configs/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integration-configs'] });
      addToast({ type: 'success', title: t('integrations.disconnected', 'Disconnected') });
    },
  });

  const testMut = useMutation({
    mutationFn: (id: string) => apiPost<{ success: boolean; message: string }>(`/v1/integrations/configs/${id}/test`, {}),
    onSuccess: (_data: { success: boolean; message: string }) => {
      if (_data.success) {
        addToast({ type: 'success', title: t('integrations.test_ok', 'Test notification sent!') });
      } else {
        addToast({ type: 'error', title: _data.message || t('integrations.test_failed', 'Test failed') });
      }
    },
    onError: () => {
      addToast({ type: 'error', title: t('integrations.test_failed', 'Test failed') });
    },
  });

  const handleConnected = useCallback(() => {
    setConnectingType(null);
    queryClient.invalidateQueries({ queryKey: ['integration-configs'] });
  }, [queryClient]);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4">
      <Breadcrumb
        items={[
          { label: t('nav.settings', 'Settings'), to: '/settings' },
          { label: t('integrations.title', 'Integrations') },
        ]}
      />

      <div>
        <h1 className="text-2xl font-bold text-primary">
          {t('integrations.title', 'Integrations')}
        </h1>
        <p className="mt-1 text-sm text-secondary">
          {t(
            'integrations.subtitle',
            'Connect external services to receive project notifications in your favorite tools.'
          )}
        </p>
      </div>

      {/* Connector cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CONNECTORS.map((connector) => {
          const existing = configsByType[connector.type] ?? [];
          const isConnectable = CONNECTABLE_TYPES.includes(connector.type);
          const isConnected = existing.length > 0;
          const Icon = connector.icon;

          return (
            <Card key={connector.nameKey} className="relative flex flex-col">
              <div className="flex flex-row items-start gap-3 pb-2">
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white ${connector.color}`}>
                  <Icon size={20} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-primary">
                      {t(connector.nameKey, connector.defaultName)}
                    </h3>
                    {isConnected && (
                      <Badge variant="success" size="sm">
                        <CheckCircle2 size={12} className="mr-1" />
                        {t('integrations.connected_label', 'Connected')}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-secondary">
                    {t(connector.descKey, connector.defaultDesc)}
                  </p>
                </div>
              </div>

              <CardContent className="flex flex-1 flex-col justify-end pt-0">
                {/* Show connected configs */}
                {existing.map((cfg) => (
                  <div
                    key={cfg.id}
                    className="mb-2 flex items-center justify-between rounded-lg bg-surface-secondary px-3 py-2 text-sm"
                  >
                    <div className="flex items-center gap-2 truncate">
                      {cfg.is_active ? (
                        <CheckCircle2 size={14} className="shrink-0 text-green-500" />
                      ) : (
                        <XCircle size={14} className="shrink-0 text-red-400" />
                      )}
                      <span className="truncate text-primary">{cfg.name}</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        onClick={() => testMut.mutate(cfg.id)}
                        disabled={testMut.isPending}
                        className="rounded p-1 text-secondary hover:bg-surface-primary hover:text-primary"
                        title={t('integrations.test', 'Test')}
                      >
                        {testMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <TestTube2 size={14} />}
                      </button>
                      <button
                        onClick={() => {
                          if (window.confirm(t('integrations.confirm_disconnect', 'Disconnect this integration?'))) {
                            deleteMut.mutate(cfg.id);
                          }
                        }}
                        className="rounded p-1 text-secondary hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20"
                        title={t('integrations.disconnect', 'Disconnect')}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}

                {/* Connect / Add another button */}
                {isConnectable && (
                  <Button
                    variant={isConnected ? 'ghost' : 'primary'}
                    size="sm"
                    className="mt-auto w-full"
                    onClick={() => setConnectingType(connector)}
                  >
                    <Plus size={14} className="mr-1" />
                    {isConnected
                      ? t('integrations.add_another', 'Add Another')
                      : t('integrations.connect', 'Connect')}
                  </Button>
                )}

                {!isConnectable && (
                  <p className="mt-2 text-center text-xs text-tertiary">
                    {t('integrations.coming_soon', 'Coming soon')}
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-8 text-secondary">
          <Loader2 size={20} className="animate-spin" />
          <span className="ml-2">{t('common.loading', 'Loading...')}</span>
        </div>
      )}

      {/* Connect modal */}
      {connectingType && (
        <ConnectModal
          connector={connectingType}
          onClose={() => setConnectingType(null)}
          onSaved={handleConnected}
        />
      )}
    </div>
  );
}
