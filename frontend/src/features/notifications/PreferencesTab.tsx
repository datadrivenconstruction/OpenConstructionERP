// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PreferencesTab — per-event-type, per-channel notification routing
 * (Wave 3 / T9).
 *
 * Renders a matrix of event-types (rows) × channels (cols).  Every cell
 * is a toggle (enable / disable for that channel) + a digest selector
 * (realtime / hourly / daily).  Changes save on blur via the
 * ``setPreference`` upsert endpoint — no global save button to avoid
 * a "Discard?" confirmation prompt every time the user switches tabs.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, XCircle, BellOff, Cable, ArrowRight } from 'lucide-react';
import clsx from 'clsx';
import { Button } from '@/shared/ui';
import {
  getEventTypes,
  getPreferences,
  setPreference,
  type NotificationChannel,
  type NotificationDigest,
  type NotificationEventType,
  type NotificationPreference,
  type NotificationPreferenceRequest,
} from './api';

// English fallbacks for the computed `notifications.preferences.channel_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const PREFERENCES_CHANNEL_LABELS: Record<string, string> = {
  inapp: 'In-app', email: 'Email', webhook: 'Webhook'
};

// English fallbacks for the computed `notifications.preferences.digest_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const PREFERENCES_DIGEST_LABELS: Record<string, string> = {
  realtime: 'Real time', hourly: 'Hourly', daily: 'Daily'
};


const CHANNELS: NotificationChannel[] = ['inapp', 'email', 'webhook'];
const DIGEST_CHOICES: NotificationDigest[] = ['realtime', 'hourly', 'daily'];

interface PrefKey {
  event_type: string;
  channel: NotificationChannel;
}

function keyOf(p: PrefKey): string {
  return `${p.event_type}::${p.channel}`;
}

interface PrefCellState {
  enabled: boolean;
  digest: NotificationDigest;
}

const DEFAULT_CELL: PrefCellState = { enabled: false, digest: 'realtime' };
/* Default for the in-app channel: enabled, realtime — matches the backend
   service's "no pref row → realtime via inapp" fallback. */
const DEFAULT_INAPP_CELL: PrefCellState = { enabled: true, digest: 'realtime' };

function buildCellMap(
  prefs: NotificationPreference[],
): Record<string, PrefCellState> {
  const out: Record<string, PrefCellState> = {};
  for (const p of prefs) {
    out[keyOf({ event_type: p.event_type, channel: p.channel })] = {
      enabled: p.enabled,
      digest: p.digest,
    };
  }
  return out;
}

export function PreferencesTab(): JSX.Element {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const eventsQuery = useQuery<NotificationEventType[]>({
    queryKey: ['notifications', 'event-types'],
    queryFn: () => getEventTypes(),
    staleTime: 60_000,
  });

  const prefsQuery = useQuery<NotificationPreference[]>({
    queryKey: ['notifications', 'preferences'],
    queryFn: () => getPreferences(),
    staleTime: 10_000,
  });

  const upsertMut = useMutation({
    mutationFn: (body: NotificationPreferenceRequest) => setPreference(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications', 'preferences'] });
    },
  });

  /* Local edit buffer so toggles feel instant; we still re-fetch on save
     success to reconcile with the server.  Keyed by event_type::channel. */
  const [draft, setDraft] = useState<Record<string, PrefCellState>>({});

  const serverMap = useMemo<Record<string, PrefCellState>>(
    () => buildCellMap(prefsQuery.data ?? []),
    [prefsQuery.data],
  );

  function cellState(et: string, ch: NotificationChannel): PrefCellState {
    const k = keyOf({ event_type: et, channel: ch });
    const drafted = draft[k];
    if (drafted) return drafted;
    const served = serverMap[k];
    if (served) return served;
    return ch === 'inapp' ? DEFAULT_INAPP_CELL : DEFAULT_CELL;
  }

  function patch(
    et: string,
    ch: NotificationChannel,
    next: Partial<PrefCellState>,
  ): void {
    const k = keyOf({ event_type: et, channel: ch });
    const prev = cellState(et, ch);
    const merged: PrefCellState = { ...prev, ...next };
    setDraft((d) => ({ ...d, [k]: merged }));
    upsertMut.mutate({
      event_type: et,
      channel: ch,
      enabled: merged.enabled,
      digest: merged.digest,
    });
  }

  if (eventsQuery.isLoading || prefsQuery.isLoading) {
    return (
      <div className="p-8 flex items-center justify-center text-content-tertiary">
        <Loader2 className="animate-spin me-2" size={16} />
        {t('common.loading', { defaultValue: 'Loading...' })}
      </div>
    );
  }

  if (eventsQuery.isError || prefsQuery.isError) {
    return (
      <div className="p-8 text-center">
        <XCircle size={24} className="mx-auto mb-2 text-semantic-error" />
        <p className="text-sm text-content-secondary mb-3">
          {t('notifications.preferences.load_error', {
            defaultValue: "Couldn't load preferences",
          })}
        </p>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            eventsQuery.refetch();
            prefsQuery.refetch();
          }}
        >
          {t('common.retry', { defaultValue: 'Try again' })}
        </Button>
      </div>
    );
  }

  const eventTypes = eventsQuery.data ?? [];

  if (eventTypes.length === 0) {
    return (
      <div className="p-12 text-center">
        <BellOff
          size={28}
          strokeWidth={1.5}
          className="mx-auto mb-2 text-content-tertiary"
        />
        <p className="text-sm text-content-secondary">
          {t('notifications.preferences.no_events', {
            defaultValue: 'No event types available',
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="mb-3 text-xs text-content-tertiary">
        {t('notifications.preferences.intro', {
          defaultValue:
            'Choose how you want to be notified for each kind of event. ' +
            'Realtime is immediate; hourly and daily batch into a digest.',
        })}
      </div>

      {/* Connected chat integrations (Telegram, Slack, Teams, Discord, ...)
          deliver these same in-app notifications, filtered by the event list
          configured on each integration. Point the user there so they can
          route events to an outside tool, not just the channels in this
          matrix. Closes the issue #279 gap: settings here did not explain or
          link the integration delivery path. */}
      <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2.5">
        <Cable size={15} className="mt-0.5 shrink-0 text-oe-blue" />
        <div className="min-w-0 text-xs text-content-secondary">
          <span>
            {t('notifications.preferences.integrations_note', {
              defaultValue:
                'Connected chat integrations also receive these notifications. ' +
                'Choose which events each one delivers on the Integrations page.',
            })}
          </span>
          <Link
            to="/integrations"
            className="ms-1.5 inline-flex items-center gap-0.5 font-medium text-oe-blue hover:underline"
          >
            {t('notifications.preferences.manage_integrations', {
              defaultValue: 'Manage integrations',
            })}
            <ArrowRight size={12} />
          </Link>
        </div>
      </div>

      <div className="rounded-xl border border-border-light bg-surface-elevated overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-secondary">
            <tr>
              <th className="text-left px-4 py-2 font-medium text-content-secondary">
                {t('notifications.preferences.col_event', {
                  defaultValue: 'Event',
                })}
              </th>
              {CHANNELS.map((ch) => (
                <th
                  key={ch}
                  className="text-left px-4 py-2 font-medium text-content-secondary"
                >
                  {t(`notifications.preferences.channel_${ch}`, {
                    defaultValue: PREFERENCES_CHANNEL_LABELS[ch] ?? ch,
                  })}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {eventTypes.map((et) => (
              <tr key={et.event_type} className="hover:bg-surface-secondary/40">
                <td className="px-4 py-2 align-top">
                  <div className="font-medium text-content-primary">
                    {t(`notifications.event.${et.event_type}.label`, {
                      defaultValue: et.description,
                    })}
                  </div>
                  <div className="text-2xs text-content-quaternary mt-0.5">
                    <span className="font-mono">{et.event_type}</span>
                    {' · '}
                    <span className="uppercase">{et.module}</span>
                  </div>
                </td>
                {CHANNELS.map((ch) => {
                  const cell = cellState(et.event_type, ch);
                  const cellKey = keyOf({ event_type: et.event_type, channel: ch });
                  const pending =
                    upsertMut.isPending &&
                    upsertMut.variables?.event_type === et.event_type &&
                    upsertMut.variables?.channel === ch;
                  return (
                    <td key={ch} className="px-4 py-2 align-top">
                      <div
                        className={clsx(
                          'flex flex-col gap-1',
                          pending && 'opacity-60',
                        )}
                      >
                        <label className="inline-flex items-center gap-2 cursor-pointer text-xs text-content-secondary">
                          <input
                            type="checkbox"
                            checked={cell.enabled}
                            onChange={(e) => {
                              patch(et.event_type, ch, {
                                enabled: e.target.checked,
                              });
                            }}
                            aria-label={`${et.event_type} ${ch} enabled`}
                          />
                          <span>
                            {cell.enabled
                              ? t('notifications.preferences.on', {
                                  defaultValue: 'On',
                                })
                              : t('notifications.preferences.off', {
                                  defaultValue: 'Off',
                                })}
                          </span>
                        </label>
                        <select
                          disabled={!cell.enabled}
                          value={cell.digest}
                          onChange={(e) => {
                            patch(et.event_type, ch, {
                              digest: e.target.value as NotificationDigest,
                            });
                          }}
                          className="h-7 text-2xs rounded-md border border-border bg-surface-primary text-content-primary disabled:opacity-40 px-1"
                          aria-label={`${et.event_type} ${ch} digest`}
                          data-cell={cellKey}
                        >
                          {DIGEST_CHOICES.map((d) => (
                            <option key={d} value={d}>
                              {t(`notifications.preferences.digest_${d}`, {
                                defaultValue: PREFERENCES_DIGEST_LABELS[d] ?? d,
                              })}
                            </option>
                          ))}
                        </select>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {upsertMut.isError && (
        <div className="mt-3 text-xs text-semantic-error">
          {t('notifications.preferences.save_error', {
            defaultValue: 'Could not save preference - please try again.',
          })}
        </div>
      )}
    </div>
  );
}
