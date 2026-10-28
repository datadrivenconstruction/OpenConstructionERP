// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings → Integrations: connect an external AI client over MCP.
 *
 * One card, top to bottom in the order a person needs it: switch MCP on, create
 * a token (its secret and the ready-made client configuration are shown once),
 * see which tokens exist and revoke one, review the changes clients proposed,
 * read the validation findings, and check the latest tool calls.
 *
 * A client never changes data here: every write tool creates a proposal that
 * waits in the assistant's Changes view, so the "waiting" line links there.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, Copy, KeyRound, ListChecks, Plug, ScrollText, ShieldCheck, Trash2 } from 'lucide-react';
import { Badge, Button, Card, ConfirmDialog, Input } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { copyToClipboard } from '@/shared/lib/browser';
import { fmtDate } from '@/shared/lib/formatters';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { listChatActions } from '@/features/erp-chat/actions/api';
import { useFloatingChatStore } from '@/features/erp-chat/useFloatingChat';
import {
  createMcpToken,
  getMcpSettings,
  getMcpValidation,
  listMcpCalls,
  listMcpTokens,
  mcpKeys,
  revokeMcpToken,
  updateMcpSettings,
  type McpCallOutcome,
  type McpTokenCreated,
  type McpValidationFinding,
} from './api';
import { buildClientConfig, buildHandshakeCheck } from './mcpClientConfig';

const EXPIRY_CHOICES = [30, 90, 365] as const;
const RATE_MIN = 1;
const RATE_MAX = 600;

const OUTCOME_VARIANT: Record<McpCallOutcome, BadgeVariant> = {
  ok: 'success',
  error: 'error',
  denied: 'warning',
  rate_limited: 'warning',
};

const SEVERITY_VARIANT: Record<string, BadgeVariant> = {
  error: 'error',
  warning: 'warning',
  info: 'blue',
};

function fmtDateTime(value: string | null): string {
  if (!value) return '';
  return fmtDate(value, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export interface McpSettingsPanelProps {
  /** Origin the client should call; defaults to the page's own origin. */
  origin?: string;
}

export function McpSettingsPanel({ origin }: McpSettingsPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const openChanges = useFloatingChatStore((s) => s.openChanges);
  const { confirm, ...confirmProps } = useConfirm();
  const serverOrigin = origin ?? (typeof window !== 'undefined' ? window.location.origin : '');

  const [tokenName, setTokenName] = useState('');
  const [expiryDays, setExpiryDays] = useState<number>(90);
  const [canPropose, setCanPropose] = useState(true);
  const [revealed, setRevealed] = useState<McpTokenCreated | null>(null);
  const [rateDraft, setRateDraft] = useState<string | null>(null);

  const settingsQ = useQuery({ queryKey: mcpKeys.settings, queryFn: getMcpSettings });
  const tokensQ = useQuery({ queryKey: mcpKeys.tokens, queryFn: listMcpTokens });
  const callsQ = useQuery({ queryKey: mcpKeys.calls, queryFn: () => listMcpCalls(25) });
  const validationQ = useQuery({ queryKey: mcpKeys.validation, queryFn: getMcpValidation });
  const pendingQ = useQuery({
    queryKey: mcpKeys.pending,
    queryFn: () => listChatActions({ source: 'mcp', status: 'proposed', limit: 1 }),
  });

  const refreshAll = () => {
    void qc.invalidateQueries({ queryKey: mcpKeys.all });
  };

  const saveSettings = useMutation({
    mutationFn: updateMcpSettings,
    onSuccess: (data) => {
      qc.setQueryData(mcpKeys.settings, data);
      setRateDraft(null);
      void qc.invalidateQueries({ queryKey: mcpKeys.validation });
    },
    onError: () => {
      addToast({ type: 'error', title: t('mcp.save_failed', { defaultValue: 'Could not save the MCP settings' }) });
    },
  });

  const createToken = useMutation({
    mutationFn: () =>
      createMcpToken({ name: tokenName.trim(), expires_in_days: expiryDays, can_propose: canPropose }),
    onSuccess: (created) => {
      setRevealed(created);
      setTokenName('');
      refreshAll();
    },
    onError: () => {
      addToast({ type: 'error', title: t('mcp.token_create_failed', { defaultValue: 'Could not create the token' }) });
    },
  });

  const revokeToken = useMutation({
    mutationFn: (id: string) => revokeMcpToken(id),
    onSuccess: (_data, id) => {
      if (revealed?.id === id) setRevealed(null);
      addToast({ type: 'success', title: t('mcp.token_revoked', { defaultValue: 'Token revoked' }) });
      refreshAll();
    },
    onError: () => {
      addToast({ type: 'error', title: t('mcp.token_revoke_failed', { defaultValue: 'Could not revoke the token' }) });
    },
  });

  const settings = settingsQ.data;
  const enabled = settings?.enabled ?? false;
  const activeTokens = useMemo(() => (tokensQ.data ?? []).filter((tk) => tk.is_active), [tokensQ.data]);
  const pendingCount = pendingQ.data?.counts.proposed ?? 0;
  const config = buildClientConfig(serverOrigin, revealed?.token);
  const rateValue = rateDraft ?? String(settings?.rate_limit_per_minute ?? 60);
  const rateNumber = Number(rateValue);
  const rateValid = Number.isInteger(rateNumber) && rateNumber >= RATE_MIN && rateNumber <= RATE_MAX;

  const copy = async (text: string) => {
    const ok = await copyToClipboard(text);
    addToast({
      type: ok ? 'success' : 'error',
      title: ok
        ? t('mcp.copied', { defaultValue: 'Copied to the clipboard' })
        : t('mcp.copy_failed', { defaultValue: 'Could not copy; select the text and copy it by hand' }),
    });
  };

  const askRevoke = async (id: string, name: string) => {
    const ok = await confirm({
      title: t('mcp.revoke_title', { defaultValue: 'Revoke this token?' }),
      message: t('mcp.revoke_message', {
        defaultValue: 'Clients using "{{name}}" lose access at once. This cannot be undone.',
        name,
      }),
      confirmLabel: t('mcp.revoke', { defaultValue: 'Revoke' }),
      variant: 'danger',
    });
    if (ok) revokeToken.mutate(id);
  };

  const findingText = (f: McpValidationFinding) =>
    t(`mcp.validation.${f.rule_id.replace(/^mcp\./, '')}`, {
      defaultValue: f.message,
      ...(f.params as Record<string, unknown>),
    });

  return (
    <Card padding="md" data-testid="mcp-settings">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-oe-blue/10 p-2 text-oe-blue">
          <Bot size={18} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-semibold text-content-primary">
            {t('mcp.title', { defaultValue: 'AI clients (MCP)' })}
          </h3>
          <p className="mt-0.5 text-sm text-content-secondary">
            {t('mcp.intro', {
              defaultValue:
                'Let a desktop assistant or IDE read your projects with your permissions. Changes it suggests wait for you to apply them.',
            })}
          </p>
        </div>
      </div>

      {/* 1. Switch and rate limit */}
      <section className="mt-5 flex flex-wrap items-end gap-4" aria-labelledby="mcp-access-heading">
        <h4 id="mcp-access-heading" className="sr-only">
          {t('mcp.access_heading', { defaultValue: 'Access' })}
        </h4>
        <label className="flex items-center gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={enabled}
            disabled={!settings || saveSettings.isPending}
            onChange={(e) => saveSettings.mutate({ enabled: e.target.checked })}
            data-testid="mcp-enabled"
          />
          {t('mcp.enable', { defaultValue: 'Allow AI clients to connect' })}
        </label>
        <div className="w-44">
          <Input
            type="number"
            min={RATE_MIN}
            max={RATE_MAX}
            label={t('mcp.rate_limit', { defaultValue: 'Tool calls per minute' })}
            value={rateValue}
            onChange={(e) => setRateDraft(e.target.value)}
            error={
              rateValid
                ? undefined
                : t('mcp.rate_limit_range', {
                    defaultValue: 'Between {{min}} and {{max}}',
                    min: RATE_MIN,
                    max: RATE_MAX,
                  })
            }
            data-testid="mcp-rate"
          />
        </div>
        {rateDraft !== null && (
          <Button
            size="sm"
            variant="secondary"
            disabled={!rateValid}
            loading={saveSettings.isPending}
            onClick={() => saveSettings.mutate({ rate_limit_per_minute: rateNumber })}
          >
            {t('mcp.save', { defaultValue: 'Save' })}
          </Button>
        )}
      </section>

      {/* 2. Create a token */}
      <section className="mt-6" aria-labelledby="mcp-new-token-heading">
        <h4 id="mcp-new-token-heading" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <KeyRound size={14} aria-hidden="true" />
          {t('mcp.new_token', { defaultValue: 'New token' })}
        </h4>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <div className="w-56">
            <Input
              label={t('mcp.token_name', { defaultValue: 'Name' })}
              placeholder={t('mcp.token_name_placeholder', { defaultValue: 'e.g. Laptop assistant' })}
              value={tokenName}
              maxLength={255}
              onChange={(e) => setTokenName(e.target.value)}
              data-testid="mcp-token-name"
            />
          </div>
          <label className="flex flex-col text-xs text-content-secondary">
            {t('mcp.expires_in', { defaultValue: 'Expires after' })}
            <select
              className="mt-1 rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
              value={expiryDays}
              onChange={(e) => setExpiryDays(Number(e.target.value))}
            >
              {EXPIRY_CHOICES.map((d) => (
                <option key={d} value={d}>
                  {t('mcp.days', { defaultValue: '{{days}} days', days: d })}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 pb-1.5 text-sm text-content-primary">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={canPropose}
              onChange={(e) => setCanPropose(e.target.checked)}
            />
            {t('mcp.can_propose', { defaultValue: 'May propose changes' })}
          </label>
          <Button
            size="sm"
            icon={<Plug size={14} />}
            disabled={!enabled || !tokenName.trim()}
            loading={createToken.isPending}
            onClick={() => createToken.mutate()}
            data-testid="mcp-create-token"
          >
            {t('mcp.create_token', { defaultValue: 'Create token' })}
          </Button>
        </div>
        {!enabled && (
          <p className="mt-2 text-xs text-content-tertiary">
            {t('mcp.enable_first', { defaultValue: 'Allow AI clients to connect first.' })}
          </p>
        )}

        {revealed && (
          <div className="mt-4 rounded-lg border border-oe-blue/30 bg-oe-blue/[0.04] p-3" data-testid="mcp-revealed">
            <p className="text-sm font-medium text-content-primary">
              {t('mcp.token_once', { defaultValue: 'Copy the token now. It is shown only once.' })}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded bg-surface-secondary px-2 py-1 text-xs" dir="ltr">
                {revealed.token}
              </code>
              <Button size="sm" variant="ghost" icon={<Copy size={14} />} onClick={() => void copy(revealed.token)}>
                {t('mcp.copy', { defaultValue: 'Copy' })}
              </Button>
            </div>
            <p className="mt-3 text-xs text-content-secondary">
              {t('mcp.config_hint', { defaultValue: 'Paste this into the MCP server list of your AI client:' })}
            </p>
            <pre
              className="mt-1 max-h-56 overflow-auto rounded bg-surface-secondary p-2 text-xs"
              dir="ltr"
              data-testid="mcp-config"
            >
              {config}
            </pre>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" icon={<Copy size={14} />} onClick={() => void copy(config)}>
                {t('mcp.copy_config', { defaultValue: 'Copy configuration' })}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                icon={<Copy size={14} />}
                onClick={() => void copy(buildHandshakeCheck(serverOrigin, revealed.token))}
              >
                {t('mcp.copy_check', { defaultValue: 'Copy connection test' })}
              </Button>
            </div>
          </div>
        )}
      </section>

      {/* 3. Existing tokens */}
      <section className="mt-6" aria-labelledby="mcp-tokens-heading">
        <h4 id="mcp-tokens-heading" className="text-sm font-semibold text-content-primary">
          {t('mcp.tokens', { defaultValue: 'Tokens' })}
        </h4>
        {(tokensQ.data ?? []).length === 0 ? (
          <p className="mt-1 text-sm text-content-tertiary">
            {t('mcp.no_tokens', { defaultValue: 'No tokens yet.' })}
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-border rounded-lg border border-border" data-testid="mcp-token-list">
            {(tokensQ.data ?? []).map((tk) => (
              <li key={tk.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                <span className="font-medium text-content-primary">{tk.name}</span>
                <code className="text-xs text-content-tertiary" dir="ltr">
                  {tk.key_prefix}…
                </code>
                <Badge size="sm" variant={tk.can_propose ? 'purple' : 'neutral'}>
                  {tk.can_propose
                    ? t('mcp.scope_propose', { defaultValue: 'Read and propose' })
                    : t('mcp.scope_read', { defaultValue: 'Read only' })}
                </Badge>
                {!tk.is_active && (
                  <Badge size="sm" variant="error">
                    {t('mcp.revoked', { defaultValue: 'Revoked' })}
                  </Badge>
                )}
                <span className="text-xs text-content-tertiary">
                  {tk.last_used_at
                    ? t('mcp.last_used', { defaultValue: 'Last used {{when}}', when: fmtDateTime(tk.last_used_at) })
                    : t('mcp.never_used', { defaultValue: 'Never used' })}
                  {tk.expires_at &&
                    ` · ${t('mcp.expires', { defaultValue: 'expires {{when}}', when: fmtDate(tk.expires_at) })}`}
                </span>
                {tk.is_active && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ms-auto"
                    icon={<Trash2 size={14} />}
                    onClick={() => void askRevoke(tk.id, tk.name)}
                    aria-label={t('mcp.revoke_named', { defaultValue: 'Revoke {{name}}', name: tk.name })}
                  >
                    {t('mcp.revoke', { defaultValue: 'Revoke' })}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-xs text-content-tertiary">
          {t('mcp.active_count', { defaultValue: 'Active: {{n}}', n: activeTokens.length })}
        </p>
      </section>

      {/* 4. Proposals waiting for review */}
      <section className="mt-6 flex flex-wrap items-center gap-3" aria-labelledby="mcp-review-heading">
        <h4 id="mcp-review-heading" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <ListChecks size={14} aria-hidden="true" />
          {t('mcp.proposals', { defaultValue: 'Proposed changes' })}
        </h4>
        <span className="text-sm text-content-secondary" data-testid="mcp-pending">
          {t('mcp.pending', { defaultValue: 'Waiting for your review: {{n}}', n: pendingCount })}
        </span>
        <Button size="sm" variant="secondary" onClick={openChanges}>
          {t('mcp.review', { defaultValue: 'Review changes' })}
        </Button>
      </section>

      {/* 5. Validation */}
      <section className="mt-6" aria-labelledby="mcp-validation-heading">
        <h4 id="mcp-validation-heading" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <ShieldCheck size={14} aria-hidden="true" />
          {t('mcp.checks', { defaultValue: 'Checks' })}
        </h4>
        {(validationQ.data?.findings ?? []).length === 0 ? (
          <p className="mt-1 text-sm text-content-secondary" data-testid="mcp-checks-ok">
            {t('mcp.checks_ok', { defaultValue: 'No problems found.' })}
          </p>
        ) : (
          <ul className="mt-2 space-y-1" data-testid="mcp-findings">
            {(validationQ.data?.findings ?? []).map((f, i) => (
              <li key={`${f.rule_id}-${f.element_ref ?? i}`} className="flex items-start gap-2 text-sm">
                <Badge size="sm" dot variant={SEVERITY_VARIANT[f.severity] ?? 'neutral'}>
                  {t(`mcp.severity.${f.severity}`, { defaultValue: f.severity })}
                </Badge>
                <span className="text-content-primary">{findingText(f)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 6. Recent tool calls */}
      <section className="mt-6" aria-labelledby="mcp-calls-heading">
        <h4 id="mcp-calls-heading" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <ScrollText size={14} aria-hidden="true" />
          {t('mcp.recent_calls', { defaultValue: 'Recent tool calls' })}
        </h4>
        {(callsQ.data ?? []).length === 0 ? (
          <p className="mt-1 text-sm text-content-tertiary">
            {t('mcp.no_calls', { defaultValue: 'No calls yet.' })}
          </p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm" data-testid="mcp-calls">
              <thead>
                <tr className="text-start text-xs text-content-tertiary">
                  <th className="py-1 pe-3 text-start font-medium">{t('mcp.col_time', { defaultValue: 'Time' })}</th>
                  <th className="py-1 pe-3 text-start font-medium">{t('mcp.col_tool', { defaultValue: 'Tool' })}</th>
                  <th className="py-1 pe-3 text-start font-medium">
                    {t('mcp.col_outcome', { defaultValue: 'Outcome' })}
                  </th>
                  <th className="py-1 text-end font-medium">{t('mcp.col_duration', { defaultValue: 'Duration' })}</th>
                </tr>
              </thead>
              <tbody>
                {(callsQ.data ?? []).map((c) => (
                  <tr key={c.id} className="border-t border-border">
                    <td className="py-1 pe-3 text-content-secondary">{fmtDateTime(c.created_at)}</td>
                    <td className="py-1 pe-3" dir="ltr">
                      <code className="text-xs">{c.tool}</code>
                    </td>
                    <td className="py-1 pe-3">
                      <Badge size="sm" variant={OUTCOME_VARIANT[c.outcome] ?? 'neutral'}>
                        {t(`mcp.outcome.${c.outcome}`, { defaultValue: c.outcome })}
                      </Badge>
                    </td>
                    <td className="py-1 text-end text-content-secondary">
                      {c.duration_ms != null
                        ? t('mcp.duration_ms', { defaultValue: '{{ms}} ms', ms: c.duration_ms })
                        : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}
