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
  Phone,
  Gamepad2,
  Workflow,
  Zap,
  Cog,
  Sheet,
  BarChart3,
  Code2,
  type LucideIcon,
} from 'lucide-react';
import { Badge, Button, Input, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

type IntegrationType = 'teams' | 'slack' | 'telegram' | 'discord' | 'whatsapp' | 'email' | 'webhook';

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

type ConnectorStatus = 'available' | 'coming_soon' | 'info_only';
type ConnectorCategory = 'notifications' | 'automation' | 'data';

interface ConnectorDef {
  type: IntegrationType;
  nameKey: string;
  defaultName: string;
  descKey: string;
  defaultDesc: string;
  icon: LucideIcon;
  color: string;
  category: ConnectorCategory;
  status: ConnectorStatus;
  fields: { key: string; label: string; placeholder: string; type?: string }[];
  setupInstructions: string;
  externalUrl?: string;
}

const CONNECTORS: ConnectorDef[] = [
  // ── Notifications ──────────────────────────────────────────────────
  {
    type: 'teams',
    nameKey: 'integrations.teams',
    defaultName: 'Microsoft Teams',
    descKey: 'integrations.teams_desc',
    defaultDesc: 'Send notifications to your Teams channel via Incoming Webhook',
    icon: MessageSquare,
    color: 'bg-[#6264A7]',
    category: 'notifications',
    status: 'available',
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
    category: 'notifications',
    status: 'available',
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
    category: 'notifications',
    status: 'available',
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
    type: 'discord',
    nameKey: 'integrations.discord',
    defaultName: 'Discord',
    descKey: 'integrations.discord_desc',
    defaultDesc: 'Send notifications to a Discord channel via webhook',
    icon: Gamepad2,
    color: 'bg-[#5865F2]',
    category: 'notifications',
    status: 'available',
    fields: [
      {
        key: 'webhook_url',
        label: 'Webhook URL',
        placeholder: 'https://discord.com/api/webhooks/...',
      },
    ],
    setupInstructions:
      '1. Open your Discord server\n2. Go to Server Settings > Integrations > Webhooks\n3. Click "New Webhook", choose a channel\n4. Copy the webhook URL and paste it here',
  },
  {
    type: 'whatsapp',
    nameKey: 'integrations.whatsapp',
    defaultName: 'WhatsApp Business',
    descKey: 'integrations.whatsapp_desc',
    defaultDesc: 'Send template notifications via Meta Cloud API',
    icon: Phone,
    color: 'bg-[#25D366]',
    category: 'notifications',
    status: 'coming_soon',
    fields: [],
    setupInstructions:
      'WhatsApp Business integration requires Meta Business verification.\nThis feature is coming in a future release.',
  },
  {
    type: 'email',
    nameKey: 'integrations.email',
    defaultName: 'Email',
    descKey: 'integrations.email_desc',
    defaultDesc: 'Receive email notifications (SMTP)',
    icon: Mail,
    color: 'bg-blue-600',
    category: 'notifications',
    status: 'coming_soon',
    fields: [],
    setupInstructions: 'Email notifications will be available in a future update.',
  },

  // ── Automation ─────────────────────────────────────────────────────
  {
    type: 'webhook',
    nameKey: 'integrations.webhook',
    defaultName: 'Webhooks',
    descKey: 'integrations.webhook_desc',
    defaultDesc: 'Send events to any URL (HTTP POST with HMAC signing)',
    icon: Globe,
    color: 'bg-gray-600',
    category: 'automation',
    status: 'info_only',
    fields: [],
    setupInstructions: 'Use the Webhooks tab in Settings to configure custom webhook endpoints.',
  },
  {
    type: 'webhook' as IntegrationType,
    nameKey: 'integrations.n8n',
    defaultName: 'n8n',
    descKey: 'integrations.n8n_desc',
    defaultDesc: 'Self-hosted workflow automation. Use our webhook URL as a trigger node.',
    icon: Workflow,
    color: 'bg-[#EA4B71]',
    category: 'automation',
    status: 'info_only',
    fields: [],
    setupInstructions:
      '1. In n8n, add a "Webhook" trigger node\n2. Copy the webhook URL from n8n\n3. Go to Settings > Webhooks in this app and add a new endpoint\n4. Paste the n8n webhook URL, select which events to forward',
    externalUrl: 'https://n8n.io',
  },
  {
    type: 'webhook' as IntegrationType,
    nameKey: 'integrations.zapier',
    defaultName: 'Zapier',
    descKey: 'integrations.zapier_desc',
    defaultDesc: 'Connect 5,000+ apps. Use our webhook events as a Zapier trigger.',
    icon: Zap,
    color: 'bg-[#FF4A00]',
    category: 'automation',
    status: 'info_only',
    fields: [],
    setupInstructions:
      '1. In Zapier, create a new Zap with "Webhooks by Zapier" as trigger\n2. Choose "Catch Hook" and copy the webhook URL\n3. Go to Settings > Webhooks and add a new endpoint with the Zapier URL\n4. Select which events to forward, then test in Zapier',
    externalUrl: 'https://zapier.com',
  },
  {
    type: 'webhook' as IntegrationType,
    nameKey: 'integrations.make',
    defaultName: 'Make (Integromat)',
    descKey: 'integrations.make_desc',
    defaultDesc: 'Visual workflow automation. Use webhook trigger to connect.',
    icon: Cog,
    color: 'bg-[#6D00CC]',
    category: 'automation',
    status: 'info_only',
    fields: [],
    setupInstructions:
      '1. In Make, create a new Scenario with a "Webhooks" module\n2. Choose "Custom webhook" and copy the URL\n3. Go to Settings > Webhooks and add a new endpoint with the Make URL\n4. Select events to forward and run a test',
    externalUrl: 'https://www.make.com',
  },

  // ── Data ───────────────────────────────────────────────────────────
  {
    type: 'email' as IntegrationType,
    nameKey: 'integrations.calendar',
    defaultName: 'Calendar',
    descKey: 'integrations.calendar_desc',
    defaultDesc: 'Subscribe in Google/Outlook Calendar (iCal feed)',
    icon: Calendar,
    color: 'bg-green-600',
    category: 'data',
    status: 'info_only',
    fields: [],
    setupInstructions: 'Calendar feeds are available per project. Go to Project Settings > Calendar.',
  },
  {
    type: 'email' as IntegrationType,
    nameKey: 'integrations.google_sheets',
    defaultName: 'Google Sheets',
    descKey: 'integrations.google_sheets_desc',
    defaultDesc: 'Export BOQ and cost data in formats compatible with Google Sheets',
    icon: Sheet,
    color: 'bg-[#0F9D58]',
    category: 'data',
    status: 'info_only',
    fields: [],
    setupInstructions:
      '1. Open your BOQ or cost report\n2. Click Export > Excel (.xlsx)\n3. Open the file in Google Sheets, or use File > Import in Google Drive',
  },
  {
    type: 'email' as IntegrationType,
    nameKey: 'integrations.power_bi',
    defaultName: 'Power BI / Tableau',
    descKey: 'integrations.power_bi_desc',
    defaultDesc: 'Connect BI tools to our REST API for custom dashboards and analytics',
    icon: BarChart3,
    color: 'bg-[#F2C811]',
    category: 'data',
    status: 'info_only',
    fields: [],
    setupInstructions:
      '1. In Power BI/Tableau, add a new Web/REST API data source\n2. Use your base URL + /api/v1/ endpoints\n3. Authenticate with your API key (Settings > API Keys)\n4. Build custom dashboards from BOQ, cost, and project data',
    externalUrl: '/api/docs',
  },
  {
    type: 'email' as IntegrationType,
    nameKey: 'integrations.rest_api',
    defaultName: 'REST API',
    descKey: 'integrations.rest_api_desc',
    defaultDesc: 'Full REST API with OpenAPI docs for custom integrations',
    icon: Code2,
    color: 'bg-slate-700',
    category: 'data',
    status: 'info_only',
    fields: [],
    setupInstructions:
      '1. Generate an API key in Settings > API Keys\n2. Browse the interactive API docs at /api/docs\n3. Use any HTTP client to integrate with your systems',
    externalUrl: '/api/docs',
  },
];

// Only these types support the connect flow
const CONNECTABLE_TYPES: IntegrationType[] = ['teams', 'slack', 'telegram', 'discord'];

const CATEGORY_LABELS: Record<ConnectorCategory, { key: string; defaultLabel: string }> = {
  notifications: { key: 'integrations.cat_notifications', defaultLabel: 'Notifications' },
  automation: { key: 'integrations.cat_automation', defaultLabel: 'Automation' },
  data: { key: 'integrations.cat_data', defaultLabel: 'Data & Analytics' },
};

const CATEGORY_ICON_STYLES: Record<ConnectorCategory, string> = {
  notifications: 'bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400',
  automation: 'bg-purple-50 text-purple-600 dark:bg-purple-950 dark:text-purple-400',
  data: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400',
};

const CATEGORY_ORDER: ConnectorCategory[] = ['notifications', 'automation', 'data'];

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
    <div className="max-w-content mx-auto animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.settings', 'Settings'), to: '/settings' },
          { label: t('integrations.title', 'Integrations') },
        ]}
        className="mb-4"
      />

      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('integrations.title', 'Integrations')}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t(
              'integrations.subtitle',
              'Connect external services to receive project notifications in your favorite tools.'
            )}
          </p>
        </div>
      </div>

      {/* Connector cards grouped by category */}
      {CATEGORY_ORDER.map((category) => {
        const categoryConnectors = CONNECTORS.filter((c) => c.category === category);
        if (categoryConnectors.length === 0) return null;
        const catLabel = CATEGORY_LABELS[category];

        return (
          <div key={category} className="mb-6">
            <h2 className="text-xs font-bold text-content-tertiary uppercase tracking-wider mb-3">
              {t(catLabel.key, catLabel.defaultLabel)}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {categoryConnectors.map((connector) => {
                const existing = configsByType[connector.type] ?? [];
                const isConnectable = CONNECTABLE_TYPES.includes(connector.type) && connector.status === 'available';
                const isConnected = existing.length > 0;
                const isComingSoon = connector.status === 'coming_soon';
                const isInfoOnly = connector.status === 'info_only';
                const Icon = connector.icon;

                return (
                  <div key={connector.nameKey} className="rounded-xl border border-border-light bg-surface-primary p-4 hover:border-border hover:shadow-sm transition-all">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2.5">
                        <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${CATEGORY_ICON_STYLES[connector.category]}`}>
                          <Icon size={18} />
                        </div>
                        <div>
                          <h3 className="text-sm font-semibold text-content-primary">
                            {t(connector.nameKey, connector.defaultName)}
                          </h3>
                          <p className="text-2xs text-content-tertiary">
                            {t(catLabel.key, catLabel.defaultLabel)}
                          </p>
                        </div>
                      </div>
                      {isConnected && (
                        <Badge variant="success" size="sm">
                          {t('integrations.connected_label', 'Connected')}
                        </Badge>
                      )}
                      {isComingSoon && (
                        <Badge variant="neutral" size="sm">
                          {t('integrations.coming_soon', 'Coming soon')}
                        </Badge>
                      )}
                      {isInfoOnly && !isConnected && (
                        <Badge variant="blue" size="sm">
                          {t('integrations.info_label', 'Info')}
                        </Badge>
                      )}
                    </div>

                    <p className="text-xs text-content-secondary mb-3">
                      {t(connector.descKey, connector.defaultDesc)}
                    </p>

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
                          <span className="truncate text-content-primary">{cfg.name}</span>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            onClick={() => testMut.mutate(cfg.id)}
                            disabled={testMut.isPending}
                            className="rounded p-1 text-content-secondary hover:bg-surface-primary hover:text-content-primary"
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
                            className="rounded p-1 text-content-secondary hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20"
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
                        variant="secondary"
                        size="sm"
                        onClick={() => setConnectingType(connector)}
                      >
                        <Plus size={14} className="mr-1" />
                        {isConnected
                          ? t('integrations.add_another', 'Add Another')
                          : t('integrations.connect', 'Connect')}
                      </Button>
                    )}

                    {/* Info-only cards: show setup hint + optional external link */}
                    {isInfoOnly && connector.externalUrl && (
                      <a
                        href={connector.externalUrl}
                        target={connector.externalUrl.startsWith('http') ? '_blank' : undefined}
                        rel={connector.externalUrl.startsWith('http') ? 'noopener noreferrer' : undefined}
                        className="text-xs text-oe-blue hover:underline"
                      >
                        {t('integrations.learn_more', 'Learn more')}
                      </a>
                    )}

                    {/* Coming soon hint at bottom */}
                    {isComingSoon && !isConnectable && (
                      <p className="text-xs text-content-tertiary">
                        {t('integrations.coming_soon_hint', 'This integration is not yet available.')}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {isLoading && (
        <div className="flex items-center justify-center py-8 text-content-secondary">
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
