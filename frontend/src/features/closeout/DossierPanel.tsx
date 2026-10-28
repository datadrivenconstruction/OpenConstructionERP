// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Handover dossier in one action: pick the scope (project, area or asset),
 * see the checklist result, choose how it leaves (download, webhook, chat
 * connector, e-mail) and assemble. Each dossier keeps its delivery log, and any
 * delivery can be sent again without rebuilding the archive.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  FolderArchive,
  Loader2,
  RotateCw,
  Send,
  XCircle,
} from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, formatFileSize } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  checkDossier,
  downloadDossier,
  getDossierConfig,
  listDossiers,
  listDossierTargets,
  putDossierConfig,
  requestDossier,
  resendDelivery,
  type Dossier,
  type DossierChannel,
  type DossierCheck,
  type DossierConfig,
  type DossierDelivery,
  type DossierScopeKind,
} from './api';

const KNOWN_CATEGORIES = [
  'as_built',
  'om_manual',
  'warranty',
  'asset_register',
  'punch_closure',
  'inspection',
  'hs_file',
  'commissioning',
  'acceptance',
  'other',
];

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

function CheckBanner({ check }: { check: DossierCheck }) {
  const { t } = useTranslation();
  const tone =
    check.check_status === 'passed'
      ? 'border-semantic-success/40 bg-semantic-success/5 text-semantic-success'
      : check.check_status === 'warnings'
        ? 'border-amber-400/50 bg-amber-50 text-amber-700 dark:bg-amber-500/10'
        : 'border-semantic-error/40 bg-semantic-error/5 text-semantic-error';
  const Icon = check.check_status === 'passed' ? CheckCircle2 : check.check_status === 'warnings' ? AlertTriangle : XCircle;
  return (
    <div className={clsx('rounded-lg border p-3', tone)} data-testid="dossier-check">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Icon size={16} />
        {check.check_status === 'passed'
          ? t('closeout.dossier.check_passed', { defaultValue: 'Checklist passed' })
          : check.check_status === 'warnings'
            ? t('closeout.dossier.check_warnings', { defaultValue: 'Checklist passed with warnings' })
            : t('closeout.dossier.check_errors', { defaultValue: 'Checklist not met' })}
      </div>
      <p className="mt-1 text-xs text-content-secondary">
        {t('closeout.dossier.check_counts', {
          defaultValue:
            '{{punch}} punch items in scope ({{open}} open) · {{systems}} commissioning systems · acceptance {{acceptance}}',
          punch: check.punch_total,
          open: check.punch_open,
          systems: check.commissioning_systems,
          acceptance: check.acceptance_signed
            ? t('closeout.dossier.acceptance_signed', { defaultValue: 'signed' })
            : check.acceptance_bound
              ? t('closeout.dossier.acceptance_unsigned', { defaultValue: 'not signed yet' })
              : t('closeout.dossier.acceptance_missing', { defaultValue: 'missing' }),
        })}
      </p>
      {check.results.length > 0 && (
        <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto">
          {check.results.map((r, i) => (
            <li key={`${r.rule_id}-${r.element_ref ?? ''}-${i}`} className="flex items-start gap-2 text-xs text-content-primary">
              <Badge variant={r.severity === 'error' ? 'error' : r.severity === 'warning' ? 'warning' : 'neutral'} size="sm">
                {r.severity === 'error'
                  ? t('closeout.dossier.severity_error', { defaultValue: 'Error' })
                  : r.severity === 'warning'
                    ? t('closeout.dossier.severity_warning', { defaultValue: 'Warning' })
                    : t('closeout.dossier.severity_info', { defaultValue: 'Info' })}
              </Badge>
              <span>
                {r.message}
                {r.suggestion && <span className="text-content-tertiary"> {r.suggestion}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ConfigEditor({
  packageId,
  config,
  categoryLabel,
}: {
  packageId: string;
  config: DossierConfig;
  categoryLabel: (cat: string) => string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const save = useMutation({
    mutationFn: (patch: Partial<DossierConfig>) => putDossierConfig(packageId, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['closeout-dossier-config', packageId] });
      qc.invalidateQueries({ queryKey: ['closeout-dossier-check', packageId] });
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });
  const toggles: { key: keyof DossierConfig; label: string }[] = [
    { key: 'require_punch_resolved', label: t('closeout.dossier.req_punch_resolved', { defaultValue: 'Every punch item in scope is closed out' }) },
    { key: 'require_punch_photos', label: t('closeout.dossier.req_punch_photos', { defaultValue: 'Closed-out punch items carry a photo' }) },
    { key: 'require_commissioning_complete', label: t('closeout.dossier.req_commissioning', { defaultValue: 'Commissioning in scope is complete' }) },
    { key: 'require_signed_acceptance', label: t('closeout.dossier.req_acceptance', { defaultValue: 'The acceptance certificate is fully signed' }) },
    { key: 'require_verified_evidence', label: t('closeout.dossier.req_verified', { defaultValue: 'Bound evidence is verified by a manager' }) },
  ];
  const cats = Array.from(new Set([...KNOWN_CATEGORIES, ...config.required_categories]));
  return (
    <div className="grid gap-4 rounded-lg border border-border-light p-3 md:grid-cols-2" data-testid="dossier-config">
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('closeout.dossier.required_categories', { defaultValue: 'Required documents' })}
        </p>
        <div className="grid grid-cols-2 gap-1">
          {cats.map((cat) => (
            <label key={cat} className="flex items-center gap-2 text-sm text-content-primary">
              <input
                type="checkbox"
                checked={config.required_categories.includes(cat)}
                disabled={save.isPending}
                onChange={(e) =>
                  save.mutate({
                    required_categories: e.target.checked
                      ? [...config.required_categories, cat]
                      : config.required_categories.filter((c) => c !== cat),
                  })
                }
              />
              {categoryLabel(cat)}
            </label>
          ))}
        </div>
      </div>
      <div className="space-y-1.5">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('closeout.dossier.rules', { defaultValue: 'Checks' })}
        </p>
        {toggles.map(({ key, label }) => (
          <label key={key} className="flex items-center gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              checked={Boolean(config[key])}
              disabled={save.isPending}
              onChange={(e) => save.mutate({ [key]: e.target.checked } as Partial<DossierConfig>)}
            />
            {label}
          </label>
        ))}
        <label className="mt-2 flex items-center gap-2 text-sm text-content-primary">
          {t('closeout.dossier.link_days', { defaultValue: 'Download link valid (days)' })}
          <input
            type="number"
            min={1}
            max={365}
            defaultValue={config.share_expires_in_days}
            className={clsx(inputCls, 'h-8 w-20')}
            onBlur={(e) => {
              const days = Number(e.target.value);
              if (Number.isFinite(days) && days >= 1 && days <= 365 && days !== config.share_expires_in_days) {
                save.mutate({ share_expires_in_days: Math.round(days) });
              }
            }}
          />
        </label>
      </div>
    </div>
  );
}

function deliveryStatusVariant(d: DossierDelivery): 'success' | 'error' | 'neutral' {
  return d.status === 'sent' ? 'success' : d.status === 'failed' ? 'error' : 'neutral';
}

export function DossierPanel({
  packageId,
  projectId,
  categoryLabel,
  canSignOff,
}: {
  packageId: string;
  projectId: string;
  categoryLabel: (cat: string) => string;
  /** Managers may send dossiers out and assemble incomplete ones. */
  canSignOff: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [scopeKind, setScopeKind] = useState<DossierScopeKind>('project');
  const [scopeValue, setScopeValue] = useState('');
  const [channel, setChannel] = useState<DossierChannel>('download');
  const [targetId, setTargetId] = useState('');
  const [recipient, setRecipient] = useState('');
  const [message, setMessage] = useState('');
  const [password, setPassword] = useState('');
  const [allowIncomplete, setAllowIncomplete] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const debouncedValue = useDebounced(scopeValue, 400);

  const configQ = useQuery({ queryKey: ['closeout-dossier-config', packageId], queryFn: () => getDossierConfig(packageId) });
  const checkQ = useQuery({
    queryKey: ['closeout-dossier-check', packageId, scopeKind, debouncedValue],
    queryFn: () => checkDossier(packageId, scopeKind, debouncedValue),
    enabled: scopeKind === 'project' || debouncedValue.trim().length > 0,
  });
  const targetsQ = useQuery({
    queryKey: ['closeout-dossier-targets', projectId],
    queryFn: () => listDossierTargets(projectId),
    enabled: channel === 'webhook' || channel === 'connector',
  });
  const dossiersQ = useQuery({
    queryKey: ['closeout-dossiers', packageId],
    queryFn: () => listDossiers(packageId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((d: Dossier) => d.status === 'queued') ? 2500 : false,
  });
  const targets = useMemo(
    () => (targetsQ.data ?? []).filter((x) => x.channel === channel),
    [targetsQ.data, channel],
  );

  const requestMut = useMutation({
    mutationFn: () =>
      requestDossier(packageId, {
        scope_kind: scopeKind,
        scope_value: scopeKind === 'project' ? null : scopeValue.trim(),
        allow_incomplete: allowIncomplete,
        deliveries:
          channel === 'download'
            ? []
            : [
                {
                  channel,
                  target_id: channel === 'email' ? undefined : targetId || undefined,
                  recipient: channel === 'email' ? recipient.trim() : undefined,
                  message: message.trim() || undefined,
                  password: password || undefined,
                },
              ],
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['closeout-dossiers', packageId] });
      addToast({
        type: 'success',
        title: t('closeout.dossier.queued', { defaultValue: 'Assembling the dossier. It appears below when ready.' }),
      });
    },
    onError: (e: unknown) =>
      addToast({
        type: 'error',
        title: t('closeout.dossier.request_failed', { defaultValue: 'The dossier could not be assembled' }),
        message: getErrorMessage(e),
      }),
  });
  const downloadMut = useMutation({
    mutationFn: (d: Dossier) => downloadDossier(d),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['closeout-dossiers', packageId] }),
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }), message: getErrorMessage(e) }),
  });
  const resendMut = useMutation({
    mutationFn: (deliveryId: string) => resendDelivery(deliveryId),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ['closeout-dossiers', packageId] });
      addToast({
        type: d.status === 'sent' ? 'success' : 'error',
        title:
          d.status === 'sent'
            ? t('closeout.dossier.resent', { defaultValue: 'Sent again' })
            : t('closeout.dossier.resend_failed', { defaultValue: 'Sending again failed' }),
        message: d.detail ?? undefined,
      });
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const check = checkQ.data;
  const blocked = check?.check_status === 'errors' && !allowIncomplete;
  const needsSignOff = channel !== 'download' || allowIncomplete;
  const targetMissing =
    (channel === 'webhook' || channel === 'connector') && !targetId
      ? true
      : channel === 'email' && !recipient.includes('@');
  const scopeMissing = scopeKind !== 'project' && !scopeValue.trim();

  const channelLabel = (c: DossierChannel) =>
    c === 'download'
      ? t('closeout.dossier.channel_download', { defaultValue: 'Download' })
      : c === 'webhook'
        ? t('closeout.dossier.channel_webhook', { defaultValue: 'Webhook' })
        : c === 'connector'
          ? t('closeout.dossier.channel_connector', { defaultValue: 'Chat connector' })
          : t('closeout.dossier.channel_email', { defaultValue: 'E-mail' });
  const scopeText = (d: Dossier) =>
    d.scope?.kind === 'area'
      ? t('closeout.dossier.scope_area_value', { defaultValue: 'Area: {{value}}', value: d.scope.value })
      : d.scope?.kind === 'asset'
        ? t('closeout.dossier.scope_asset_value', { defaultValue: 'Asset: {{value}}', value: d.scope.value })
        : t('closeout.dossier.scope_project', { defaultValue: 'Whole project' });
  const dossierStatus = (d: Dossier) =>
    d.status === 'queued'
      ? t('closeout.dossier.status_queued', { defaultValue: 'Assembling' })
      : d.status === 'built'
        ? t('closeout.dossier.status_built', { defaultValue: 'Ready' })
        : d.status === 'delivered'
          ? t('closeout.dossier.status_delivered', { defaultValue: 'Delivered' })
          : t('closeout.dossier.status_failed', { defaultValue: 'Failed' });

  return (
    <Card className="p-5" data-testid="dossier-panel">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold text-content-primary">
            <FolderArchive size={18} className="text-oe-blue" />
            {t('closeout.dossier.title', { defaultValue: 'Handover dossier' })}
          </h3>
          <p className="mt-1 text-sm text-content-secondary">
            {t('closeout.dossier.intro', {
              defaultValue:
                'One action assembles the as-built documents, warranties, O&M manuals, test and commissioning certificates, the resolved punch list with its photos and the signed acceptance into an index PDF and a ZIP, checks it against your checklist and sends it.',
            })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowConfig((v) => !v)}
          className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
        >
          {showConfig ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {t('closeout.dossier.edit_checklist', { defaultValue: 'Checklist' })}
        </button>
      </div>

      {showConfig && configQ.data && (
        <div className="mb-4">
          <ConfigEditor packageId={packageId} config={configQ.data} categoryLabel={categoryLabel} />
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-3">
        <label className="text-xs font-medium text-content-secondary">
          {t('closeout.dossier.scope', { defaultValue: 'Scope' })}
          <select
            className={clsx(inputCls, 'mt-1')}
            value={scopeKind}
            onChange={(e) => setScopeKind(e.target.value as DossierScopeKind)}
            data-testid="dossier-scope-kind"
          >
            <option value="project">{t('closeout.dossier.scope_project', { defaultValue: 'Whole project' })}</option>
            <option value="area">{t('closeout.dossier.scope_area', { defaultValue: 'One area' })}</option>
            <option value="asset">{t('closeout.dossier.scope_asset', { defaultValue: 'One asset' })}</option>
          </select>
        </label>
        {scopeKind !== 'project' && (
          <label className="text-xs font-medium text-content-secondary md:col-span-2">
            {scopeKind === 'area'
              ? t('closeout.dossier.area_label', { defaultValue: 'Area (as recorded on items, e.g. "Level 2")' })
              : t('closeout.dossier.asset_label', { defaultValue: 'Asset reference (element id, plant item id or tag)' })}
            <input
              className={clsx(inputCls, 'mt-1')}
              value={scopeValue}
              onChange={(e) => setScopeValue(e.target.value)}
              data-testid="dossier-scope-value"
            />
          </label>
        )}
      </div>

      <div className="mt-3">
        {checkQ.isFetching && !check ? (
          <div className="flex items-center gap-2 text-sm text-content-tertiary">
            <Loader2 size={14} className="animate-spin" />
            {t('closeout.dossier.checking', { defaultValue: 'Checking...' })}
          </div>
        ) : check ? (
          <CheckBanner check={check} />
        ) : null}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <label className="text-xs font-medium text-content-secondary">
          {t('closeout.dossier.deliver_via', { defaultValue: 'Deliver via' })}
          <select
            className={clsx(inputCls, 'mt-1')}
            value={channel}
            onChange={(e) => {
              setChannel(e.target.value as DossierChannel);
              setTargetId('');
            }}
            data-testid="dossier-channel"
          >
            {(['download', 'webhook', 'connector', 'email'] as DossierChannel[]).map((c) => (
              <option key={c} value={c}>
                {channelLabel(c)}
              </option>
            ))}
          </select>
        </label>
        {(channel === 'webhook' || channel === 'connector') && (
          <label className="text-xs font-medium text-content-secondary md:col-span-2">
            {t('closeout.dossier.target', { defaultValue: 'Send to' })}
            <select className={clsx(inputCls, 'mt-1')} value={targetId} onChange={(e) => setTargetId(e.target.value)}>
              <option value="">
                {targets.length === 0
                  ? t('closeout.dossier.no_targets', { defaultValue: 'None configured. Add one under Integrations.' })
                  : t('closeout.dossier.pick_target', { defaultValue: 'Choose...' })}
              </option>
              {targets.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.kind ? `${x.name} (${x.kind})` : x.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {channel === 'email' && (
          <label className="text-xs font-medium text-content-secondary md:col-span-2">
            {t('closeout.dossier.recipient', { defaultValue: 'Recipient e-mail' })}
            <input
              type="email"
              className={clsx(inputCls, 'mt-1')}
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
            />
          </label>
        )}
        {channel !== 'download' && (
          <>
            <label className="text-xs font-medium text-content-secondary md:col-span-2">
              {t('closeout.dossier.message', { defaultValue: 'Message (optional)' })}
              <input className={clsx(inputCls, 'mt-1')} value={message} onChange={(e) => setMessage(e.target.value)} />
            </label>
            <label className="text-xs font-medium text-content-secondary">
              {t('closeout.dossier.password', { defaultValue: 'Link password (optional)' })}
              <input
                type="password"
                autoComplete="new-password"
                className={clsx(inputCls, 'mt-1')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
          </>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {check?.check_status === 'errors' && canSignOff && (
          <label className="flex items-center gap-2 text-sm text-content-secondary">
            <input type="checkbox" checked={allowIncomplete} onChange={(e) => setAllowIncomplete(e.target.checked)} />
            {t('closeout.dossier.allow_incomplete', { defaultValue: 'Assemble anyway, marked incomplete' })}
          </label>
        )}
        <Button
          variant="primary"
          icon={<Send size={14} />}
          loading={requestMut.isPending}
          disabled={blocked || targetMissing || scopeMissing || (needsSignOff && !canSignOff) || !check}
          onClick={() => requestMut.mutate()}
          data-testid="dossier-assemble"
        >
          {channel === 'download'
            ? t('closeout.dossier.assemble', { defaultValue: 'Assemble dossier' })
            : t('closeout.dossier.assemble_send', { defaultValue: 'Assemble and send' })}
        </Button>
        {needsSignOff && !canSignOff && (
          <span className="text-xs text-content-tertiary">
            {t('closeout.dossier.manager_only', { defaultValue: 'Sending a dossier out is a manager sign-off.' })}
          </span>
        )}
      </div>

      {(dossiersQ.data ?? []).length > 0 && (
        <div className="mt-6">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
            {t('closeout.dossier.history', { defaultValue: 'Dossiers and delivery log' })}
          </h4>
          <div className="space-y-3">
            {(dossiersQ.data ?? []).map((d) => (
              <div key={d.id} className="rounded-lg border border-border-light p-3" data-testid={`dossier-${d.id}`}>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge variant={d.status === 'failed' ? 'error' : d.status === 'queued' ? 'neutral' : 'success'} size="sm">
                    {d.status === 'queued' && <Loader2 size={10} className="mr-1 inline animate-spin" />}
                    {dossierStatus(d)}
                  </Badge>
                  <span className="font-medium text-content-primary">{scopeText(d)}</span>
                  <span className="text-xs text-content-tertiary">{fmtDate(d.created_at, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                  {d.size_bytes != null && (
                    <span className="text-xs text-content-tertiary">
                      {formatFileSize(d.size_bytes)} · {t('closeout.dossier.files', { defaultValue: '{{count}} files', count: d.file_count ?? 0 })}
                    </span>
                  )}
                  {d.check_status && d.check_status !== 'passed' && (
                    <Badge variant={d.check_status === 'errors' ? 'error' : 'warning'} size="sm">
                      {d.check_status === 'errors'
                        ? t('closeout.dossier.incomplete', { defaultValue: 'Incomplete' })
                        : t('closeout.dossier.with_warnings', { defaultValue: 'With warnings' })}
                    </Badge>
                  )}
                  {d.sha256 && (
                    <span className="font-mono text-[10px] text-content-quaternary" title={d.sha256}>
                      SHA-256 {d.sha256.slice(0, 12)}
                    </span>
                  )}
                  <span className="flex-1" />
                  {(d.status === 'built' || d.status === 'delivered') && (
                    <Button variant="secondary" size="sm" icon={<Download size={13} />} onClick={() => downloadMut.mutate(d)} loading={downloadMut.isPending && downloadMut.variables?.id === d.id}>
                      {t('closeout.dossier.download', { defaultValue: 'Download' })}
                    </Button>
                  )}
                </div>
                {d.error && <p className="mt-1 text-xs text-semantic-error">{d.error}</p>}
                {d.deliveries.length > 0 && (
                  <table className="mt-2 w-full text-xs">
                    <thead className="text-left text-content-tertiary">
                      <tr>
                        <th className="py-1 font-medium">{t('closeout.dossier.col_channel', { defaultValue: 'Channel' })}</th>
                        <th className="py-1 font-medium">{t('closeout.dossier.col_target', { defaultValue: 'Recipient' })}</th>
                        <th className="py-1 font-medium">{t('closeout.dossier.col_status', { defaultValue: 'Status' })}</th>
                        <th className="py-1 font-medium">{t('closeout.dossier.col_when', { defaultValue: 'When' })}</th>
                        <th className="py-1 font-medium">{t('closeout.dossier.col_link', { defaultValue: 'Link valid until' })}</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {d.deliveries.map((x) => (
                        <tr key={x.id} className="border-t border-border-light">
                          <td className="py-1">{channelLabel(x.channel)}</td>
                          <td className="py-1">{x.target_label ?? x.recipient ?? '-'}</td>
                          <td className="py-1">
                            <Badge variant={deliveryStatusVariant(x)} size="sm">
                              {x.status === 'sent'
                                ? t('closeout.dossier.delivery_sent', { defaultValue: 'Sent' })
                                : x.status === 'failed'
                                  ? t('closeout.dossier.delivery_failed', { defaultValue: 'Failed' })
                                  : t('closeout.dossier.delivery_pending', { defaultValue: 'Pending' })}
                            </Badge>
                            {x.detail && x.status === 'failed' && <span className="ml-1 text-content-tertiary">{x.detail}</span>}
                          </td>
                          <td className="py-1">{x.delivered_at ? fmtDate(x.delivered_at, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'}</td>
                          <td className="py-1">{x.share_expires_at ? fmtDate(x.share_expires_at, { dateStyle: 'short' }) : '-'}</td>
                          <td className="py-1 text-right">
                            {x.channel !== 'download' && canSignOff && (
                              <button
                                type="button"
                                className="inline-flex items-center gap-1 text-oe-blue hover:underline disabled:opacity-50"
                                onClick={() => resendMut.mutate(x.id)}
                                disabled={resendMut.isPending}
                              >
                                <RotateCw size={11} />
                                {t('closeout.dossier.resend', { defaultValue: 'Send again' })}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
