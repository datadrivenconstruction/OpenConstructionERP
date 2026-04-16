import { useState, useCallback, useRef, useEffect } from 'react';
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
  Info,
  Copy,
  Check,
  ExternalLink,
  type LucideIcon,
} from 'lucide-react';
import { Badge, Button, Input, Breadcrumb, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

type IntegrationType =
  | 'teams'
  | 'slack'
  | 'telegram'
  | 'discord'
  | 'whatsapp'
  | 'email'
  | 'webhook';

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

interface ConnectorField {
  key: string;
  label: string;
  placeholder: string;
  type?: string;
}

interface SetupStep {
  text: string;
}

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
  fields: ConnectorField[];
  setupSteps: SetupStep[];
  infoText?: string;
  calendarFeedUrl?: boolean;
  eventOptions?: string[];
  externalUrl?: string;
}

const AVAILABLE_EVENTS = [
  'task.created',
  'task.updated',
  'task.completed',
  'rfi.created',
  'rfi.answered',
  'invoice.created',
  'invoice.approved',
  'document.uploaded',
  'project.updated',
  'boq.changed',
];

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
    setupSteps: [
      { text: 'Open your Teams channel' },
      { text: 'Click "..." → "Connectors" → "Incoming Webhook"' },
      { text: 'Name it "OpenConstructionERP" and click "Create"' },
      { text: 'Copy the webhook URL' },
      { text: 'Paste it below' },
    ],
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
    setupSteps: [
      { text: 'Go to api.slack.com/apps → Create New App' },
      { text: 'Enable "Incoming Webhooks"' },
      { text: 'Add webhook to your channel' },
      { text: 'Copy the webhook URL' },
      { text: 'Paste it below' },
    ],
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
    setupSteps: [
      { text: 'Open Telegram, search @BotFather' },
      { text: 'Send /newbot and follow instructions' },
      { text: 'Copy the bot token' },
      { text: 'Add the bot to your group/channel' },
      { text: 'Get the chat ID (send a message, then check getUpdates)' },
    ],
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
    setupSteps: [
      { text: 'Open your Discord server settings' },
      { text: 'Go to Integrations → Webhooks → New Webhook' },
      { text: 'Name it and select the channel' },
      { text: 'Copy the webhook URL' },
    ],
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
    setupSteps: [],
  },
  {
    type: 'email',
    nameKey: 'integrations.email',
    defaultName: 'Email (SMTP)',
    descKey: 'integrations.email_desc',
    defaultDesc: 'Receive email notifications via custom SMTP server',
    icon: Mail,
    color: 'bg-blue-600',
    category: 'notifications',
    status: 'available',
    fields: [
      {
        key: 'smtp_host',
        label: 'SMTP Host',
        placeholder: 'smtp.gmail.com',
      },
      {
        key: 'smtp_port',
        label: 'Port',
        placeholder: '587',
      },
      {
        key: 'smtp_username',
        label: 'Username',
        placeholder: 'you@example.com',
      },
      {
        key: 'smtp_password',
        label: 'Password',
        placeholder: 'App password or SMTP password',
        type: 'password',
      },
      {
        key: 'from_email',
        label: 'From Email',
        placeholder: 'noreply@yourcompany.com',
      },
    ],
    setupSteps: [
      { text: 'Get your SMTP server details from your email provider' },
      {
        text: 'Common: smtp.gmail.com:587 (Gmail), smtp.office365.com:587 (Outlook)',
      },
      { text: 'Fill in the fields below' },
    ],
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
    status: 'available',
    fields: [
      {
        key: 'webhook_url',
        label: 'Endpoint URL',
        placeholder: 'https://your-server.com/webhooks/openconstructionerp',
      },
      {
        key: 'signing_secret',
        label: 'Secret (optional)',
        placeholder: 'HMAC signing secret for payload verification',
        type: 'password',
      },
    ],
    setupSteps: [
      { text: 'Enter the URL where you want to receive events' },
      { text: 'Optionally add a signing secret for HMAC verification' },
      { text: 'Select which events to subscribe to' },
    ],
    eventOptions: AVAILABLE_EVENTS,
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
    setupSteps: [],
    infoText:
      'Use our Webhook integration as a trigger node in n8n. Point your n8n Webhook trigger to: /api/v1/integrations/webhooks',
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
    setupSteps: [],
    infoText:
      'Use our Webhook integration as a trigger in Zapier Webhooks. Create a "Catch Hook" Zap and point it to our webhook endpoint.',
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
    setupSteps: [],
    infoText:
      'Use our Webhook integration as a trigger in Make. Create a "Custom Webhook" module and subscribe to our events.',
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
    status: 'available',
    fields: [],
    calendarFeedUrl: true,
    setupSteps: [
      { text: 'Copy the calendar feed URL below' },
      { text: 'In Google Calendar: "Other calendars" → "From URL"' },
      { text: 'In Outlook: "Add calendar" → "Subscribe from web"' },
      { text: 'Paste the URL and subscribe' },
    ],
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
    setupSteps: [],
    infoText:
      'Export your data as Excel from any module → open in Google Sheets. Use File > Import in Google Drive for direct import.',
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
    setupSteps: [],
    infoText:
      'Connect Power BI or Tableau to our REST API. Use /api/docs for endpoint reference and authenticate with your API key.',
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
    setupSteps: [],
    infoText:
      'Full REST API with interactive OpenAPI docs available at /api/docs. Generate an API key in Settings to authenticate.',
    externalUrl: '/api/docs',
  },
];

// Only these connector types + statuses support the connect flow
const CONNECTABLE_TYPES: IntegrationType[] = [
  'teams',
  'slack',
  'telegram',
  'discord',
  'email',
  'webhook',
];

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
  return apiGet('/v1/integrations/configs/');
}

/* ── Info Popover ─────────────────────────────────────────────────────── */

function InfoPopover({
  text,
  externalUrl,
}: {
  text: string;
  externalUrl?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className="rounded p-1 text-content-tertiary hover:text-oe-blue hover:bg-surface-secondary transition-colors"
        title={t('integrations.show_info', 'Show setup info')}
      >
        <Info size={15} />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-72 rounded-lg border border-border-light bg-surface-primary p-3 shadow-lg animate-fade-in">
          <p className="text-xs text-content-secondary leading-relaxed">{text}</p>
          {externalUrl && (
            <a
              href={externalUrl}
              target={externalUrl.startsWith('http') ? '_blank' : undefined}
              rel={externalUrl.startsWith('http') ? 'noopener noreferrer' : undefined}
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
            >
              {t('integrations.learn_more', 'Learn more')}
              <ExternalLink size={11} />
            </a>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Calendar Card (inline, no modal) ─────────────────────────────────── */

function CalendarFeedSection() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [copied, setCopied] = useState(false);
  const feedUrl = `${window.location.origin}/api/v1/integrations/calendar/feed.ics`;

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(feedUrl).then(() => {
      setCopied(true);
      addToast({
        type: 'success',
        title: t('integrations.url_copied', 'URL copied to clipboard'),
      });
      setTimeout(() => setCopied(false), 2000);
    });
  }, [feedUrl, addToast, t]);

  return (
    <div className="mt-2">
      <p className="mb-2 text-2xs text-content-tertiary">
        {t('integrations.calendar_hint', 'Subscribe in Google Calendar or Outlook:')}
      </p>
      <div className="flex items-center gap-1.5">
        <code className="flex-1 truncate rounded bg-surface-secondary px-2 py-1.5 text-2xs text-content-secondary font-mono">
          {feedUrl}
        </code>
        <Button variant="secondary" size="sm" onClick={handleCopy} className="shrink-0">
          {copied ? <Check size={13} className="mr-1" /> : <Copy size={13} className="mr-1" />}
          {copied ? t('common.copied', 'Copied') : t('common.copy', 'Copy')}
        </Button>
      </div>
    </div>
  );
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
  const [selectedEvents, setSelectedEvents] = useState<string[]>(
    connector.eventOptions ? [] : ['*']
  );
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  const toggleEvent = useCallback((event: string) => {
    setSelectedEvents((prev) =>
      prev.includes(event) ? prev.filter((e) => e !== event) : [...prev, event]
    );
  }, []);

  const selectAllEvents = useCallback(() => {
    if (connector.eventOptions) {
      setSelectedEvents((prev) =>
        prev.length === connector.eventOptions!.length ? [] : [...connector.eventOptions!]
      );
    }
  }, [connector.eventOptions]);

  const handleTest = useCallback(async () => {
    // Validate all fields are filled before testing
    for (const f of connector.fields) {
      if (f.key === 'signing_secret') continue; // optional field
      if (!fieldValues[f.key]?.trim()) {
        addToast({
          type: 'error',
          title: t('common.validation', 'Validation'),
          message: `${f.label} ${t('common.is_required', 'is required')}`,
        });
        return;
      }
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiPost<{ success: boolean; message: string }>(
        '/v1/integrations/configs/test-connection',
        {
          integration_type: connector.type,
          config: fieldValues,
        }
      );
      setTestResult(result);
      if (result.success) {
        addToast({
          type: 'success',
          title: t('integrations.test_ok', 'Test notification sent!'),
        });
      } else {
        addToast({
          type: 'error',
          title: result.message || t('integrations.test_failed', 'Test failed'),
        });
      }
    } catch {
      setTestResult({ success: false, message: 'Connection failed' });
      addToast({
        type: 'error',
        title: t('integrations.test_failed', 'Test failed'),
      });
    } finally {
      setTesting(false);
    }
  }, [connector, fieldValues, addToast, t]);

  const handleSave = useCallback(async () => {
    // Validate all fields are filled
    for (const f of connector.fields) {
      if (f.key === 'signing_secret') continue; // optional field
      if (!fieldValues[f.key]?.trim()) {
        addToast({
          type: 'error',
          title: t('common.validation', 'Validation'),
          message: `${f.label} ${t('common.is_required', 'is required')}`,
        });
        return;
      }
    }
    // Webhook with event options must have at least one event selected
    if (connector.eventOptions && selectedEvents.length === 0) {
      addToast({
        type: 'error',
        title: t('common.validation', 'Validation'),
        message: t('integrations.select_events', 'Select at least one event'),
      });
      return;
    }
    setSaving(true);
    try {
      await apiPost('/v1/integrations/configs/', {
        integration_type: connector.type,
        name: name.trim() || connector.defaultName,
        config: fieldValues,
        events: connector.eventOptions ? selectedEvents : ['*'],
      });
      addToast({
        type: 'success',
        title: t('integrations.connected', 'Connected successfully'),
      });
      onSaved();
    } catch {
      addToast({
        type: 'error',
        title: t('integrations.connect_failed', 'Connection failed'),
      });
    } finally {
      setSaving(false);
    }
  }, [connector, name, fieldValues, selectedEvents, addToast, t, onSaved]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl bg-surface-primary p-6 shadow-xl">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg text-white ${connector.color}`}
            >
              <connector.icon size={20} />
            </div>
            <h2 className="text-lg font-semibold text-primary">
              {t('integrations.connect_title', 'Connect {{name}}', {
                name: connector.defaultName,
              })}
            </h2>
          </div>
          <button onClick={onClose} className="text-secondary hover:text-primary">
            <X size={20} />
          </button>
        </div>

        {/* Step-by-step setup instructions */}
        {connector.setupSteps.length > 0 && (
          <div className="mb-4 rounded-lg bg-surface-secondary p-3">
            <p className="mb-2 text-xs font-semibold text-primary">
              {t('integrations.setup_steps', 'Setup instructions')}
            </p>
            <ol className="space-y-1.5">
              {connector.setupSteps.map((step, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-content-secondary">
                  <span className="flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-2xs font-bold text-oe-blue mt-0.5">
                    {i + 1}
                  </span>
                  <span className="leading-relaxed">{step.text}</span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Name field */}
        <div className="mb-3">
          <label className="mb-1 block text-sm font-medium text-primary">
            {t('common.name', 'Name')}
          </label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={connector.defaultName}
          />
        </div>

        {/* Connector-specific fields */}
        {connector.fields.map((field) => (
          <div key={field.key} className="mb-3">
            <label className="mb-1 block text-sm font-medium text-primary">
              {field.label}
              {field.key === 'signing_secret' && (
                <span className="ml-1 text-2xs text-content-tertiary font-normal">
                  ({t('common.optional', 'optional')})
                </span>
              )}
            </label>
            <Input
              type={field.type || 'text'}
              value={fieldValues[field.key] || ''}
              onChange={(e) =>
                setFieldValues((prev) => ({ ...prev, [field.key]: e.target.value }))
              }
              placeholder={field.placeholder}
            />
          </div>
        ))}

        {/* Event selection for webhooks */}
        {connector.eventOptions && (
          <div className="mb-3">
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-sm font-medium text-primary">
                {t('integrations.events', 'Events to subscribe')}
              </label>
              <button
                onClick={selectAllEvents}
                className="text-2xs text-oe-blue hover:underline"
              >
                {selectedEvents.length === connector.eventOptions.length
                  ? t('common.deselect_all', 'Deselect all')
                  : t('common.select_all', 'Select all')}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-1.5 rounded-lg bg-surface-secondary p-2.5">
              {connector.eventOptions.map((event) => (
                <label
                  key={event}
                  className="flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 text-xs text-content-secondary hover:bg-surface-primary transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedEvents.includes(event)}
                    onChange={() => toggleEvent(event)}
                    className="h-3.5 w-3.5 rounded border-border text-oe-blue focus:ring-oe-blue"
                  />
                  <code className="text-2xs">{event}</code>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Test result feedback */}
        {testResult && (
          <div
            className={`mb-3 rounded-lg px-3 py-2 text-xs ${
              testResult.success
                ? 'bg-semantic-success-bg text-semantic-success'
                : 'bg-semantic-error-bg text-semantic-error'
            }`}
          >
            {testResult.success
              ? t('integrations.test_success_msg', 'Connection test passed successfully!')
              : testResult.message ||
                t('integrations.test_failed_msg', 'Connection test failed. Check your settings.')}
          </div>
        )}

        {/* Actions */}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button variant="secondary" onClick={handleTest} disabled={testing}>
            {testing ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <TestTube2 size={14} className="mr-1" />
            )}
            {t('integrations.test_connection', 'Test Connection')}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 size={16} className="mr-1 animate-spin" />}
            {t('common.save', 'Save')}
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
  const { confirm, ...confirmProps } = useConfirm();
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
      addToast({
        type: 'success',
        title: t('integrations.disconnected', 'Disconnected'),
      });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('integrations.disconnect_failed', { defaultValue: 'Failed to disconnect' }), message: err.message });
    },
  });

  const testMut = useMutation({
    mutationFn: (id: string) =>
      apiPost<{ success: boolean; message: string }>(
        `/v1/integrations/configs/${id}/test`,
        {}
      ),
    onSuccess: (_data: { success: boolean; message: string }) => {
      if (_data.success) {
        addToast({
          type: 'success',
          title: t('integrations.test_ok', 'Test notification sent!'),
        });
      } else {
        addToast({
          type: 'error',
          title: _data.message || t('integrations.test_failed', 'Test failed'),
        });
      }
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('integrations.test_failed', 'Test failed'),
      });
    },
  });

  const handleConnected = useCallback(() => {
    setConnectingType(null);
    queryClient.invalidateQueries({ queryKey: ['integration-configs'] });
  }, [queryClient]);

  return (
    <div className="w-full animate-fade-in">
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
                const isConnectable =
                  CONNECTABLE_TYPES.includes(connector.type) &&
                  connector.status === 'available';
                const isConnected = existing.length > 0;
                const isComingSoon = connector.status === 'coming_soon';
                const isInfoOnly = connector.status === 'info_only';
                const Icon = connector.icon;

                return (
                  <div
                    key={connector.nameKey}
                    className={`rounded-xl border border-border-light bg-surface-primary p-4 transition-all ${
                      isComingSoon
                        ? 'opacity-50 pointer-events-none'
                        : 'hover:border-border hover:shadow-sm'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2.5">
                        <div
                          className={`flex h-9 w-9 items-center justify-center rounded-lg ${CATEGORY_ICON_STYLES[connector.category]}`}
                        >
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
                      <div className="flex items-center gap-1">
                        {/* Info popover for info-only connectors */}
                        {isInfoOnly && connector.infoText && (
                          <InfoPopover
                            text={connector.infoText}
                            externalUrl={connector.externalUrl}
                          />
                        )}
                        {isConnected && (
                          <Badge variant="success" size="sm">
                            {t('integrations.connected_label', 'Connected')}
                          </Badge>
                        )}
                        {!isConnected && isConnectable && (
                          <Badge variant="success" size="sm" dot>
                            {t('integrations.available', 'Available')}
                          </Badge>
                        )}
                        {isComingSoon && (
                          <Badge variant="neutral" size="sm">
                            {t('integrations.coming_soon', 'Coming soon')}
                          </Badge>
                        )}
                        {isInfoOnly && !isConnected && (
                          <Badge variant="blue" size="sm">
                            {t('integrations.guide_label', 'Guide')}
                          </Badge>
                        )}
                      </div>
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
                            {testMut.isPending ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : (
                              <TestTube2 size={14} />
                            )}
                          </button>
                          <button
                            onClick={async () => {
                              const ok = await confirm({
                                title: t('integrations.confirm_disconnect_title', { defaultValue: 'Disconnect integration?' }),
                                message: t('integrations.confirm_disconnect', 'Disconnect this integration?'),
                              });
                              if (ok) deleteMut.mutate(cfg.id);
                            }}
                            className="rounded p-1 text-content-secondary hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20"
                            title={t('integrations.disconnect', 'Disconnect')}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    ))}

                    {/* Calendar feed URL (inline, no modal needed) */}
                    {connector.calendarFeedUrl && <CalendarFeedSection />}

                    {/* Connect / Add another button */}
                    {isConnectable && !connector.calendarFeedUrl && (
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

                    {/* Info-only cards: show external link */}
                    {isInfoOnly && connector.externalUrl && !connector.infoText && (
                      <a
                        href={connector.externalUrl}
                        target={
                          connector.externalUrl.startsWith('http') ? '_blank' : undefined
                        }
                        rel={
                          connector.externalUrl.startsWith('http')
                            ? 'noopener noreferrer'
                            : undefined
                        }
                        className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
                      >
                        {t('integrations.learn_more', 'Learn more')}
                        <ExternalLink size={11} />
                      </a>
                    )}

                    {/* Coming soon hint at bottom */}
                    {isComingSoon && (
                      <p className="text-xs text-content-tertiary">
                        {t(
                          'integrations.coming_soon_hint',
                          'This integration is not yet available.'
                        )}
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
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
