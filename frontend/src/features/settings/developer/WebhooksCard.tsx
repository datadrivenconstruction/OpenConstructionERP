// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Settings, Developer: signed webhooks. Create, send a test, read deliveries and send one again. */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { History, Plus, Send, Trash2, Webhook as WebhookIcon } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Input,
  SideDrawer,
  WideModal,
  WideModalField,
} from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { fmtDate } from '@/shared/lib/formatters';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import {
  MAX_ATTEMPTS,
  createWebhook,
  deleteWebhook,
  describeError,
  developerKeys,
  listDeliveries,
  listWebhookEvents,
  listWebhooks,
  redeliver,
  testWebhook,
  type DeliveryStatus,
  type Webhook,
  type WebhookCreated,
  type WebhookDelivery,
} from './developerApi';
import { SecretReveal } from './SecretReveal';

const STATUS_VARIANT: Record<DeliveryStatus, BadgeVariant> = {
  delivered: 'success',
  pending: 'neutral',
  retrying: 'warning',
  dead: 'error',
};

const STATUS_LABEL: Record<DeliveryStatus, string> = {
  delivered: 'Delivered',
  pending: 'Pending',
  retrying: 'Retrying',
  dead: 'Failed',
};

function fmtDateTime(value: string | null): string {
  if (!value) return '';
  return fmtDate(value, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function WebhooksCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const hooksQ = useQuery({ queryKey: developerKeys.webhooks, queryFn: listWebhooks });
  const eventsQ = useQuery({ queryKey: developerKeys.events, queryFn: listWebhookEvents });

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [secret, setSecret] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [revealed, setRevealed] = useState<WebhookCreated | null>(null);
  const [drawerFor, setDrawerFor] = useState<Webhook | null>(null);

  const deliveriesQ = useQuery({
    queryKey: developerKeys.deliveries(drawerFor?.id ?? ''),
    queryFn: () => listDeliveries(drawerFor!.id),
    enabled: drawerFor !== null,
  });

  const refreshHooks = () => void qc.invalidateQueries({ queryKey: developerKeys.webhooks });
  const refreshDeliveries = (id: string) => void qc.invalidateQueries({ queryKey: developerKeys.deliveries(id) });
  const fail = (title: string) => (err: unknown) =>
    addToast({ type: 'error', title, message: describeError(err) });

  const secretTooShort = secret.length > 0 && secret.length < 24;
  const urlValid = /^https?:\/\/\S+$/i.test(url.trim());

  const create = useMutation({
    mutationFn: () =>
      createWebhook({
        name: name.trim(),
        url: url.trim(),
        events: picked.length ? picked : ['*'],
        ...(secret ? { secret } : {}),
      }),
    onSuccess: (created) => {
      setRevealed(created);
      setCreating(false);
      setName('');
      setUrl('');
      setSecret('');
      setPicked([]);
      setFilter('');
      refreshHooks();
    },
    onError: fail(t('developer.hook_create_failed', { defaultValue: 'Could not create the webhook' })),
  });

  const sendTest = useMutation({
    mutationFn: (h: Webhook) => testWebhook(h.id),
    onSuccess: (delivery, h) => {
      const ok = delivery.status === 'delivered';
      addToast({
        type: ok ? 'success' : 'error',
        title: ok
          ? t('developer.test_ok', { defaultValue: 'Test event delivered' })
          : t('developer.test_failed', { defaultValue: 'Test event was not accepted' }),
        message: ok ? undefined : delivery.last_error || undefined,
      });
      refreshHooks();
      refreshDeliveries(h.id);
    },
    onError: fail(t('developer.test_error', { defaultValue: 'Could not send the test event' })),
  });

  const resend = useMutation({
    mutationFn: (d: WebhookDelivery) => redeliver(d.id),
    onSuccess: (_d, d) => {
      refreshDeliveries(d.webhook_id);
      refreshHooks();
    },
    onError: fail(t('developer.redeliver_failed', { defaultValue: 'Could not send the delivery again' })),
  });

  const remove = useMutation({
    mutationFn: (h: Webhook) => deleteWebhook(h.id),
    onSuccess: refreshHooks,
    onError: fail(t('developer.hook_delete_failed', { defaultValue: 'Could not delete the webhook' })),
  });

  const askDelete = async (h: Webhook) => {
    const ok = await confirm({
      title: t('developer.hook_delete_title', { defaultValue: 'Delete this webhook?' }),
      message: t('developer.hook_delete_message', {
        defaultValue: '"{{name}}" stops receiving events and its delivery history is removed.',
        name: h.name,
      }),
      confirmLabel: t('developer.delete', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (ok) remove.mutate(h);
  };

  const visibleEvents = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const all = eventsQ.data ?? [];
    return (q ? all.filter((e) => e.name.toLowerCase().includes(q)) : all).slice(0, 200);
  }, [eventsQ.data, filter]);

  const toggle = (ev: string) =>
    setPicked((cur) => (cur.includes(ev) ? cur.filter((e) => e !== ev) : [...cur, ev]));

  const statusText = (s: DeliveryStatus) =>
    t(`developer.status.${s}`, { defaultValue: STATUS_LABEL[s] });

  const hooks = hooksQ.data ?? [];
  const deliveries = deliveriesQ.data ?? [];

  return (
    <Card padding="md" data-testid="developer-webhooks">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-oe-blue/10 p-2 text-oe-blue">
          <WebhookIcon size={18} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-semibold text-content-primary">
            {t('developer.hooks_title', { defaultValue: 'Webhooks' })}
          </h3>
          <p className="mt-0.5 text-sm text-content-secondary">
            {t('developer.hooks_intro', {
              defaultValue:
                'Get a signed HTTPS call when something happens here. Failed calls are retried for about 6 hours.',
            })}
          </p>
        </div>
        <Button size="sm" icon={<Plus size={14} />} onClick={() => setCreating(true)} data-testid="developer-hook-new">
          {t('developer.hook_new', { defaultValue: 'New webhook' })}
        </Button>
      </div>

      {revealed && (
        <SecretReveal
          testId="developer-hook-reveal"
          title={t('developer.secret_once', { defaultValue: 'Copy the signing secret now. It is shown only once.' })}
          hint={t('developer.secret_use', {
            defaultValue: 'Use it to check the X-OE-Signature header on every call you receive.',
          })}
          secret={revealed.signing_secret}
          onDone={() => setRevealed(null)}
        />
      )}

      {hooks.length === 0 ? (
        <p className="mt-4 text-sm text-content-tertiary">
          {t('developer.no_hooks', { defaultValue: 'No webhooks yet.' })}
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm" data-testid="developer-hook-table">
            <thead>
              <tr className="text-left text-xs text-content-tertiary">
                <th className="py-1 pr-3 font-medium">{t('developer.col_name', { defaultValue: 'Name' })}</th>
                <th className="py-1 pr-3 font-medium">{t('developer.col_events', { defaultValue: 'Events' })}</th>
                <th className="py-1 pr-3 font-medium">{t('developer.col_last', { defaultValue: 'Last call' })}</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {hooks.map((h) => (
                <tr key={h.id} data-testid={`developer-hook-${h.id}`}>
                  <td className="py-2 pr-3">
                    <div className="font-medium text-content-primary">{h.name}</div>
                    <div className="max-w-[18rem] truncate text-xs text-content-tertiary" dir="ltr" title={h.url}>
                      {h.url}
                    </div>
                    {!h.is_active && (
                      <Badge size="sm" variant="warning">
                        {t('developer.inactive', { defaultValue: 'Off' })}
                      </Badge>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-content-secondary">
                    {h.events.length === 0 || h.events.includes('*')
                      ? t('developer.all_events', { defaultValue: 'All events' })
                      : t('developer.n_events', { defaultValue: '{{count}} events', count: h.events.length })}
                  </td>
                  <td className="py-2 pr-3 text-content-secondary">
                    {h.last_triggered_at ? (
                      <>
                        {fmtDateTime(h.last_triggered_at)}
                        {h.last_status_code ? (
                          <Badge
                            size="sm"
                            className="ml-2"
                            variant={h.last_status_code >= 200 && h.last_status_code < 300 ? 'success' : 'error'}
                          >
                            {h.last_status_code}
                          </Badge>
                        ) : null}
                      </>
                    ) : (
                      t('developer.never', { defaultValue: 'Never' })
                    )}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Send size={14} />}
                      disabled={sendTest.isPending}
                      onClick={() => sendTest.mutate(h)}
                      data-testid={`developer-hook-test-${h.id}`}
                    >
                      {t('developer.send_test', { defaultValue: 'Send test' })}
                    </Button>
                    <Button size="sm" variant="ghost" icon={<History size={14} />} onClick={() => setDrawerFor(h)}>
                      {t('developer.deliveries', { defaultValue: 'Deliveries' })}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={14} />}
                      onClick={() => void askDelete(h)}
                      aria-label={t('developer.delete_named', { defaultValue: 'Delete {{name}}', name: h.name })}
                    />
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
        title={t('developer.hook_new_title', { defaultValue: 'New webhook' })}
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              {t('developer.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              disabled={!name.trim() || !urlValid || secretTooShort}
              loading={create.isPending}
              onClick={() => create.mutate()}
              data-testid="developer-hook-create"
            >
              {t('developer.hook_create', { defaultValue: 'Create webhook' })}
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
          />
          <Input
            label={t('developer.field_url', { defaultValue: 'Endpoint URL' })}
            hint={t('developer.field_url_hint', { defaultValue: 'Must be https and reachable from the internet.' })}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            dir="ltr"
            placeholder="https://"
          />
          <Input
            label={t('developer.field_secret', { defaultValue: 'Signing secret (optional)' })}
            hint={t('developer.field_secret_hint', {
              defaultValue: 'At least 24 characters. Leave empty and the server generates one.',
            })}
            error={
              secretTooShort
                ? t('developer.secret_short', { defaultValue: 'Use at least 24 characters.' })
                : undefined
            }
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            dir="ltr"
            autoComplete="off"
          />
          <WideModalField
            label={t('developer.field_events', { defaultValue: 'Events' })}
            hint={t('developer.field_events_hint', {
              defaultValue: 'Tick none to receive every event. {{count}} selected.',
              count: picked.length,
            })}
          >
            <Input
              aria-label={t('developer.filter_events', { defaultValue: 'Filter events' })}
              placeholder={t('developer.filter_events', { defaultValue: 'Filter events' })}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              dir="ltr"
            />
            <div className="mt-2 max-h-56 space-y-1 overflow-y-auto rounded-lg border border-border p-2">
              {visibleEvents.map((ev) => (
                <label key={ev.name} className="flex items-center gap-2 text-sm text-content-primary">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={picked.includes(ev.name)}
                    onChange={() => toggle(ev.name)}
                  />
                  <span dir="ltr">{t(ev.i18n_key, { defaultValue: ev.name })}</span>
                  <span className="text-xs text-content-tertiary" dir="ltr">
                    {ev.name}
                  </span>
                </label>
              ))}
            </div>
          </WideModalField>
        </div>
      </WideModal>

      <SideDrawer
        open={drawerFor !== null}
        onClose={() => setDrawerFor(null)}
        title={t('developer.deliveries_title', { defaultValue: 'Deliveries' })}
        subtitle={drawerFor?.name}
      >
        {deliveries.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('developer.no_deliveries', { defaultValue: 'Nothing sent yet.' })}
          </p>
        ) : (
          <ul className="divide-y divide-border" data-testid="developer-deliveries">
            {deliveries.map((d) => (
              <li key={d.id} className="py-2 text-sm" data-testid={`developer-delivery-${d.id}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge size="sm" variant={STATUS_VARIANT[d.status] ?? 'neutral'}>
                    {statusText(d.status)}
                  </Badge>
                  <span className="font-medium text-content-primary" dir="ltr">
                    {d.event_type}
                  </span>
                  {d.status_code ? <span className="text-xs text-content-tertiary">{d.status_code}</span> : null}
                  <span className="ms-auto text-xs text-content-tertiary">{fmtDateTime(d.created_at)}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
                  <span>
                    {t('developer.attempt', {
                      defaultValue: 'Attempt {{n}} of {{max}}',
                      n: d.attempt,
                      max: MAX_ATTEMPTS,
                    })}
                  </span>
                  {d.status === 'retrying' && d.next_retry_at && (
                    <span>
                      {t('developer.next_retry', { defaultValue: 'Next try {{when}}', when: fmtDateTime(d.next_retry_at) })}
                    </span>
                  )}
                  {d.last_error && <span className="truncate text-content-tertiary">{d.last_error}</span>}
                  {d.status !== 'delivered' && (
                    <Button
                      size="sm"
                      variant="secondary"
                      className="ms-auto"
                      disabled={resend.isPending}
                      onClick={() => resend.mutate(d)}
                      data-testid={`developer-redeliver-${d.id}`}
                    >
                      {t('developer.redeliver', { defaultValue: 'Redeliver' })}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </SideDrawer>

      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}
