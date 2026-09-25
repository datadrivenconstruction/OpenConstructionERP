// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
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
import {
  Badge,
  Button,
  Input,
  Breadcrumb,
  ConfirmDialog,
  SkeletonGrid,
  ModuleGuideButton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { integrationsGuide } from './integrationsGuide';
import { calendarFeedUrl } from './calendarFeed';
import { DismissibleInfo, IntroRichText } from '@/shared/ui/DismissibleInfo';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { copyToClipboard } from '@/shared/lib/browser';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
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

type ConnectorStatus = 'available' | 'info_only';
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
  /**
   * Optional human labels for {@link eventOptions}, keyed by the raw option
   * value. When present the checkbox shows the label (with the raw value as a
   * caption) instead of a bare code chip - used by the chat connectors whose
   * options are notification-type slugs rather than self-describing names.
   */
  eventOptionLabels?: Record<string, { label: string; defaultLabel: string }>;
  /**
   * When true and {@link eventOptions} are present, the connect form starts
   * with every event selected (so the connector's out-of-box behaviour is
   * "deliver everything", which the user can then narrow). Used by the chat
   * connectors to preserve their historical "all events" default. The raw
   * webhook connector leaves this off so the user must opt into events.
   */
  defaultAllEvents?: boolean;
  externalUrl?: string;
}

/**
 * Event names a raw outbound *webhook* may subscribe to. These are the
 * dotted event-bus names the webhook sink emits.
 */
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

/**
 * Notification types a connected chat connector (Telegram / Slack / Teams /
 * Discord) may be limited to. These are the per-recipient ``notification_type``
 * slugs the notification-to-connector bridge filters on (NOT the dotted
 * event-bus names used by the raw webhook sink above), so selecting one here
 * actually narrows what the bot delivers. Leaving the connector on "all" (the
 * historical default) keeps every notification flowing. New comment activity
 * in project discussions is ``comment_added`` (issue #279).
 */
const NOTIFICATION_EVENT_OPTIONS = [
  'comment_added',
  'file_comment_mention',
  'rfi_assigned',
  'rfi_responded',
  'task_assigned',
  'risk_assigned',
  'submittal_submitted',
  'submittal_approved',
  'submittal_rejected',
  'transmittal_issued',
  'transmittal_acknowledged',
  'approval_overdue',
  'approval_escalated',
  'validation_errors',
  'validation_warnings',
  'clash_high_severity',
];

const NOTIFICATION_EVENT_LABELS: Record<
  string,
  { label: string; defaultLabel: string }
> = {
  comment_added: {
    label: 'integrations.evt.comment_added',
    defaultLabel: 'New discussion comment',
  },
  file_comment_mention: {
    label: 'integrations.evt.file_comment_mention',
    defaultLabel: 'Mentioned in a file comment',
  },
  rfi_assigned: { label: 'integrations.evt.rfi_assigned', defaultLabel: 'RFI assigned to you' },
  rfi_responded: { label: 'integrations.evt.rfi_responded', defaultLabel: 'RFI response received' },
  task_assigned: { label: 'integrations.evt.task_assigned', defaultLabel: 'Task assigned to you' },
  risk_assigned: { label: 'integrations.evt.risk_assigned', defaultLabel: 'Risk assigned to you' },
  submittal_submitted: {
    label: 'integrations.evt.submittal_submitted',
    defaultLabel: 'Submittal submitted',
  },
  submittal_approved: {
    label: 'integrations.evt.submittal_approved',
    defaultLabel: 'Submittal approved',
  },
  submittal_rejected: {
    label: 'integrations.evt.submittal_rejected',
    defaultLabel: 'Submittal rejected',
  },
  transmittal_issued: {
    label: 'integrations.evt.transmittal_issued',
    defaultLabel: 'Transmittal issued',
  },
  transmittal_acknowledged: {
    label: 'integrations.evt.transmittal_acknowledged',
    defaultLabel: 'Transmittal acknowledged',
  },
  approval_overdue: {
    label: 'integrations.evt.approval_overdue',
    defaultLabel: 'Approval overdue',
  },
  approval_escalated: {
    label: 'integrations.evt.approval_escalated',
    defaultLabel: 'Approval escalated',
  },
  validation_errors: {
    label: 'integrations.evt.validation_errors',
    defaultLabel: 'Validation errors',
  },
  validation_warnings: {
    label: 'integrations.evt.validation_warnings',
    defaultLabel: 'Validation warnings',
  },
  clash_high_severity: {
    label: 'integrations.evt.clash_high_severity',
    defaultLabel: 'High-severity clash',
  },
};

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
    eventOptions: NOTIFICATION_EVENT_OPTIONS,
    eventOptionLabels: NOTIFICATION_EVENT_LABELS,
    defaultAllEvents: true,
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
    eventOptions: NOTIFICATION_EVENT_OPTIONS,
    eventOptionLabels: NOTIFICATION_EVENT_LABELS,
    defaultAllEvents: true,
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
    eventOptions: NOTIFICATION_EVENT_OPTIONS,
    eventOptionLabels: NOTIFICATION_EVENT_LABELS,
    defaultAllEvents: true,
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
    eventOptions: NOTIFICATION_EVENT_OPTIONS,
    eventOptionLabels: NOTIFICATION_EVENT_LABELS,
    defaultAllEvents: true,
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
  const projectId = useActiveProjectId();
  const feedUrl = calendarFeedUrl(window.location.origin, projectId);

  const handleCopy = useCallback(() => {
    copyToClipboard(feedUrl).then(() => {
      setCopied(true);
      addToast({
        type: 'success',
        title: t('integrations.url_copied', 'URL copied to clipboard'),
      });
      setTimeout(() => setCopied(false), 2000);
    });
  }, [feedUrl, addToast, t]);

  if (!projectId) {
    return (
      <p className="mt-2 text-2xs text-content-tertiary">
        {t('integrations.calendar_needs_project', 'Pick a project in the header switcher to get its feed address.')}
      </p>
    );
  }

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
      <p className="mt-1.5 text-2xs text-content-tertiary">
        {t('integrations.calendar_token_hint', 'Replace API_KEY with one of your API keys before subscribing.')}
      </p>
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
  const [selectedEvents, setSelectedEvents] = useState<string[]>(() => {
    if (!connector.eventOptions) return ['*'];
    // Chat connectors start with everything selected (their historical
    // default); the raw webhook connector starts empty so the user opts in.
    return connector.defaultAllEvents ? [...connector.eventOptions] : [];
  });
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
        '/v1/integrations/configs/test-connection/',
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
        // When every listed option is kept selected (the default for chat
        // connectors), send the wildcard so EVERY notification type is
        // forwarded - including event types not in the curated option list
        // (portal invites, change orders, contracts, and so on). Only when the
        // user deliberately narrows the selection do we send the explicit set.
        events:
          connector.eventOptions && selectedEvents.length < connector.eventOptions.length
            ? selectedEvents
            : ['*'],
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
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="text-secondary hover:text-primary"
          >
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

        {/* Event selection. The raw webhook connector subscribes to dotted
            event-bus names; the chat connectors (which carry eventOptionLabels)
            choose which notification types the bot delivers. */}
        {connector.eventOptions && (
          <div className="mb-3">
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-sm font-medium text-primary">
                {connector.eventOptionLabels
                  ? t('integrations.events_notify', 'Notify me about')
                  : t('integrations.events', 'Events to subscribe')}
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
            {connector.eventOptionLabels && (
              <p className="mb-1.5 text-2xs text-content-tertiary">
                {t('integrations.events_notify_hint', {
                  defaultValue:
                    'This connector delivers the in-app notifications you pick here. Leave all selected to receive everything.',
                })}
              </p>
            )}
            <div className="grid grid-cols-2 gap-1.5 rounded-lg bg-surface-secondary p-2.5">
              {connector.eventOptions.map((event) => {
                const meta = connector.eventOptionLabels?.[event];
                return (
                  <label
                    key={event}
                    className="flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 text-xs text-content-secondary hover:bg-surface-primary transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={selectedEvents.includes(event)}
                      onChange={() => toggleEvent(event)}
                      className="h-3.5 w-3.5 shrink-0 rounded border-border text-oe-blue focus:ring-oe-blue"
                    />
                    {meta ? (
                      <span className="truncate" title={meta.defaultLabel}>
                        {t(meta.label, meta.defaultLabel)}
                      </span>
                    ) : (
                      <code className="text-2xs">{event}</code>
                    )}
                  </label>
                );
              })}
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
  const navigate = useNavigate();
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
    <div className="space-y-5 animate-fade-in">
      {/* Single-item trail auto-hides (canon §2.1): a non-project admin page
          renders no breadcrumb, matching its sibling admin surfaces. The
          Settings link stays reachable from the DismissibleInfo link pills. */}
      <Breadcrumb
        items={[
          { label: t('integrations.title', 'Integrations') },
        ]}
      />

      <PageHeader
        srTitle={t('integrations.title', 'Integrations')}
        subtitle={t(
          'integrations.subtitle',
          'Connect external services to receive project notifications in your favorite tools.'
        )}
        actions={<ModuleGuideButton content={integrationsGuide} />}
      />

      <DismissibleInfo
        storageKey="integrations"
        title={t('integrations.intro_title', {
          defaultValue: 'Get project events into the tools you use',
        })}
        more={t('integrations.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('integrations.intro_more')} /> : undefined}
        links={[
          {
            label: t('integrations.link_webhook_targets', { defaultValue: 'Webhook targets' }),
            onClick: () => navigate('/admin/webhook-targets'),
          },
          {
            label: t('notifications.title', { defaultValue: 'Notifications' }),
            onClick: () => navigate('/notifications'),
          },
          {
            label: t('nav.settings', { defaultValue: 'Settings' }),
            onClick: () => navigate('/settings'),
          },
        ]}
      >
        {t('integrations.intro_body', {
          defaultValue:
            'Connect Teams, Slack, Telegram, Discord, email or a signed webhook and pick which events (tasks, RFIs, invoices, document uploads, BOQ changes) trigger a message, with a Test button before you save. Subscribe to the calendar feed for due dates, or point n8n, Zapier, Make and BI tools at the REST API for everything else.',
        })}
      </DismissibleInfo>

      {/* Connector cards grouped by category */}
      <div className="space-y-6">
      {CATEGORY_ORDER.map((category) => {
        const categoryConnectors = CONNECTORS.filter((c) => c.category === category);
        if (categoryConnectors.length === 0) return null;
        const catLabel = CATEGORY_LABELS[category];

        return (
          <div key={category}>
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
                const isInfoOnly = connector.status === 'info_only';
                const Icon = connector.icon;

                return (
                  <div
                    key={connector.nameKey}
                    className="rounded-xl border border-border-light bg-surface-primary p-4 transition-all hover:border-border hover:shadow-sm"
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
                                confirmLabel: t('integrations.disconnect', 'Disconnect'),
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
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
      </div>

      {isLoading && <SkeletonGrid items={6} />}

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
