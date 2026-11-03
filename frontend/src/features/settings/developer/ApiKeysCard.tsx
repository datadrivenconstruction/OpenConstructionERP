// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Settings, Developer: personal API keys. Create, rotate and revoke; the plaintext is shown once. */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Badge, Button, Card, ConfirmDialog, Input, WideModal, WideModalField } from '@/shared/ui';
import { fmtDate } from '@/shared/lib/formatters';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import {
  createApiKey,
  describeError,
  developerKeys,
  listApiKeys,
  listApiScopes,
  parseCidrs,
  revokeApiKey,
  rotateApiKey,
  type ApiKey,
  type ApiKeyCreated,
  type ApiScope,
} from './developerApi';
import { SecretReveal } from './SecretReveal';

const EXPIRY_CHOICES = [30, 90, 365, 730] as const;
const RATE_MAX = 6000;

const scopeLabel = (t: (k: string, o?: Record<string, unknown>) => string, s: { name: string; i18n_key: string }) =>
  t(s.i18n_key, { defaultValue: s.name });

function fmtDateTime(value: string | null): string {
  if (!value) return '';
  return fmtDate(value, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function ApiKeysCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const keysQ = useQuery({ queryKey: developerKeys.apiKeys, queryFn: listApiKeys });
  const scopesQ = useQuery({ queryKey: developerKeys.scopes, queryFn: listApiScopes });

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [expiry, setExpiry] = useState<number>(90);
  const [rate, setRate] = useState('');
  const [cidrs, setCidrs] = useState('');
  const [revealed, setRevealed] = useState<ApiKeyCreated | null>(null);

  const refresh = () => void qc.invalidateQueries({ queryKey: developerKeys.apiKeys });
  const fail = (title: string) => (err: unknown) =>
    addToast({ type: 'error', title, message: describeError(err) });

  const resetForm = () => {
    setName('');
    setPicked([]);
    setExpiry(90);
    setRate('');
    setCidrs('');
  };

  const rateNumber = rate.trim() === '' ? null : Number(rate);
  const rateValid = rateNumber === null || (Number.isInteger(rateNumber) && rateNumber >= 1 && rateNumber <= RATE_MAX);
  const cidrList = parseCidrs(cidrs);
  const cidrsValid = cidrList.length <= 20;

  const create = useMutation({
    mutationFn: () =>
      createApiKey({
        name: name.trim(),
        permissions: picked,
        expires_in_days: expiry,
        rate_limit_per_min: rateNumber,
        allowed_cidrs: cidrList,
      }),
    onSuccess: (created) => {
      setRevealed(created);
      setCreating(false);
      resetForm();
      refresh();
    },
    onError: fail(t('developer.key_create_failed', { defaultValue: 'Could not create the key' })),
  });

  const rotate = useMutation({
    mutationFn: (id: string) => rotateApiKey(id),
    onSuccess: (created) => {
      setRevealed(created);
      refresh();
    },
    onError: fail(t('developer.key_rotate_failed', { defaultValue: 'Could not rotate the key' })),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('developer.key_revoked', { defaultValue: 'Key revoked' }) });
      refresh();
    },
    onError: fail(t('developer.key_revoke_failed', { defaultValue: 'Could not revoke the key' })),
  });

  const askRotate = async (k: ApiKey) => {
    const ok = await confirm({
      title: t('developer.rotate_title', { defaultValue: 'Rotate this key?' }),
      message: t('developer.rotate_message', {
        defaultValue:
          'A new key with the same name, scopes and limits is created. "{{name}}" keeps working for 24 more hours so you can switch over.',
        name: k.name,
      }),
      confirmLabel: t('developer.rotate', { defaultValue: 'Rotate' }),
      variant: 'warning',
    });
    if (ok) rotate.mutate(k.id);
  };

  const askRevoke = async (k: ApiKey) => {
    const ok = await confirm({
      title: t('developer.revoke_title', { defaultValue: 'Revoke this key?' }),
      message: t('developer.revoke_message', {
        defaultValue: 'Anything using "{{name}}" loses access at once. This cannot be undone.',
        name: k.name,
      }),
      confirmLabel: t('developer.revoke', { defaultValue: 'Revoke' }),
      variant: 'danger',
    });
    if (ok) revoke.mutate(k.id);
  };

  const groups = useMemo(() => {
    const by = new Map<string, ApiScope[]>();
    for (const s of scopesQ.data ?? []) by.set(s.module, [...(by.get(s.module) ?? []), s]);
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [scopesQ.data]);

  const toggle = (scope: string) =>
    setPicked((cur) => (cur.includes(scope) ? cur.filter((s) => s !== scope) : [...cur, scope]));

  const keys = keysQ.data ?? [];

  return (
    <Card padding="md" data-testid="developer-keys">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-oe-blue/10 p-2 text-oe-blue">
          <KeyRound size={18} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-semibold text-content-primary">
            {t('developer.keys_title', { defaultValue: 'API keys' })}
          </h3>
          <p className="mt-0.5 text-sm text-content-secondary">
            {t('developer.keys_intro', {
              defaultValue:
                'Let a BI, ERP or accounting system call this server as you. A key never has more rights than you do; scopes narrow it further.',
            })}
          </p>
        </div>
        <Button size="sm" icon={<Plus size={14} />} onClick={() => setCreating(true)} data-testid="developer-key-new">
          {t('developer.key_new', { defaultValue: 'New key' })}
        </Button>
      </div>

      {revealed && (
        <SecretReveal
          testId="developer-key-reveal"
          title={t('developer.key_once', { defaultValue: 'Copy the key now. It is shown only once.' })}
          hint={t('developer.key_use', { defaultValue: 'Send it in the X-API-Key header.' })}
          secret={revealed.key}
          onDone={() => setRevealed(null)}
        />
      )}

      {keys.length === 0 ? (
        <p className="mt-4 text-sm text-content-tertiary">{t('developer.no_keys', { defaultValue: 'No keys yet.' })}</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm" data-testid="developer-key-table">
            <thead>
              <tr className="text-left text-xs text-content-tertiary">
                <th className="py-1 pr-3 font-medium">{t('developer.col_name', { defaultValue: 'Name' })}</th>
                <th className="py-1 pr-3 font-medium">{t('developer.col_scopes', { defaultValue: 'Scopes' })}</th>
                <th className="py-1 pr-3 font-medium">{t('developer.col_last_used', { defaultValue: 'Last used' })}</th>
                <th className="py-1 pr-3 font-medium">{t('developer.col_requests', { defaultValue: 'Requests' })}</th>
                <th className="py-1 pr-3 font-medium">{t('developer.col_expires', { defaultValue: 'Expires' })}</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {keys.map((k) => (
                <tr key={k.id} data-testid={`developer-key-${k.id}`}>
                  <td className="py-2 pr-3">
                    <div className="font-medium text-content-primary">{k.name}</div>
                    <code className="text-xs text-content-tertiary" dir="ltr">
                      {k.key_prefix}…
                    </code>
                  </td>
                  <td className="py-2 pr-3">
                    {k.permissions.length === 0 ? (
                      <Badge size="sm" variant="warning">
                        {t('developer.scope_all', { defaultValue: 'All of your rights' })}
                      </Badge>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {k.permissions.map((p) => (
                          <Badge key={p} size="sm" variant="neutral">
                            {t(`developer.scope.${p}`, { defaultValue: p })}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-content-secondary">
                    {k.last_used_at ? fmtDateTime(k.last_used_at) : t('developer.never', { defaultValue: 'Never' })}
                  </td>
                  <td className="py-2 pr-3 tabular-nums text-content-secondary">{k.request_count}</td>
                  <td className="py-2 pr-3 text-content-secondary">
                    {k.expires_at ? fmtDateTime(k.expires_at) : t('developer.no_expiry', { defaultValue: 'No expiry' })}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<RefreshCw size={14} />}
                      disabled={rotate.isPending}
                      onClick={() => void askRotate(k)}
                      aria-label={t('developer.rotate_named', { defaultValue: 'Rotate {{name}}', name: k.name })}
                    >
                      {t('developer.rotate', { defaultValue: 'Rotate' })}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={14} />}
                      disabled={revoke.isPending}
                      onClick={() => void askRevoke(k)}
                      aria-label={t('developer.revoke_named', { defaultValue: 'Revoke {{name}}', name: k.name })}
                    >
                      {t('developer.revoke', { defaultValue: 'Revoke' })}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <WideModal
        open={creating}
        onClose={() => setCreating(false)}
        busy={create.isPending}
        title={t('developer.key_new_title', { defaultValue: 'New API key' })}
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              {t('developer.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              disabled={!name.trim() || !rateValid || !cidrsValid}
              loading={create.isPending}
              onClick={() => create.mutate()}
              data-testid="developer-key-create"
            >
              {t('developer.key_create', { defaultValue: 'Create key' })}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label={t('developer.field_name', { defaultValue: 'Name' })}
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={255}
            data-testid="developer-key-name"
          />
          <WideModalField
            label={t('developer.field_scopes', { defaultValue: 'Scopes' })}
            hint={t('developer.field_scopes_hint', {
              defaultValue: 'Tick none to give the key all of your rights. Fewer is safer.',
            })}
          >
            <div className="max-h-56 space-y-2 overflow-y-auto rounded-lg border border-border p-2">
              {groups.map(([module, scopes]) => (
                <fieldset key={module}>
                  <legend className="text-xs font-semibold uppercase text-content-tertiary">{module}</legend>
                  <div className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
                    {scopes.map((s) => (
                      <label key={s.name} className="flex items-center gap-2 text-sm text-content-primary">
                        <input
                          type="checkbox"
                          className="h-4 w-4"
                          checked={picked.includes(s.name)}
                          onChange={() => toggle(s.name)}
                        />
                        {scopeLabel(t, s)}
                      </label>
                    ))}
                  </div>
                </fieldset>
              ))}
            </div>
          </WideModalField>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <WideModalField label={t('developer.field_expiry', { defaultValue: 'Expires after' })}>
              <select
                className="w-full rounded-md border border-border bg-surface-primary px-2 py-2 text-sm text-content-primary"
                value={expiry}
                onChange={(e) => setExpiry(Number(e.target.value))}
              >
                {EXPIRY_CHOICES.map((d) => (
                  <option key={d} value={d}>
                    {t('developer.days', { defaultValue: '{{days}} days', days: d })}
                  </option>
                ))}
              </select>
            </WideModalField>
            <Input
              type="number"
              min={1}
              max={RATE_MAX}
              label={t('developer.field_rate', { defaultValue: 'Requests per minute (optional)' })}
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              error={
                rateValid
                  ? undefined
                  : t('developer.rate_invalid', { defaultValue: 'Enter a whole number from 1 to 6000.' })
              }
            />
          </div>
          <WideModalField
            label={t('developer.field_cidrs', { defaultValue: 'Allowed networks (optional)' })}
            hint={t('developer.field_cidrs_hint', {
              defaultValue: 'CIDR blocks such as 203.0.113.0/24, separated by commas or spaces. Up to 20. Empty allows any address.',
            })}
            error={cidrsValid ? undefined : t('developer.cidrs_too_many', { defaultValue: 'At most 20 networks.' })}
          >
            <textarea
              className="w-full rounded-md border border-border bg-surface-primary px-2 py-2 text-sm text-content-primary"
              rows={2}
              dir="ltr"
              value={cidrs}
              onChange={(e) => setCidrs(e.target.value)}
            />
          </WideModalField>
        </div>
      </WideModal>

      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}
