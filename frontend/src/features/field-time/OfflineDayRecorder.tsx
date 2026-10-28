// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <OfflineDayRecorder> - record one day's hours where there is no signal.
 *
 * A basement, a lift shaft, a rural site. The ordinary editor writes each line
 * straight to the server, so a day booked without a link is a day lost. This
 * composes the whole day on the device first and sends it as one entry: online
 * that is a single request, offline it goes into a local queue and replays when
 * the link comes back.
 *
 * The entry key is minted once, when the composer is opened, and travels with
 * every replay of that day. That is what lets the server answer a redelivery
 * with the timesheet it already wrote instead of booking the hours twice.
 *
 * The panel says which of the two happened, in those words. "Saved" and
 * "waiting for a signal" are different facts, and a foreman who is told the
 * first when the second is true will never look at the day again.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CloudOff,
  Cloud,
  RefreshCw,
  Trash2,
  Save,
  CheckCircle2,
  AlertTriangle,
  Clock,
} from 'lucide-react';
import { Button, Badge, CollapsibleSection } from '@/shared/ui';
import { Toggle } from '@/shared/ui/Toggle';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { todayLocalISO } from '@/shared/lib/dates';
import { listResources } from '@/features/resources/api';
import { listEquipment } from '@/features/equipment/api';
import { listVariationRequests } from '@/features/variations/api';
import type { QueuedOp } from '@/shared/lib/offline';
import { LineComposer } from './LineComposer';
import type { PickOption } from './TimesheetLineRow';
import { useFieldTimeOfflineSync } from './useFieldTimeOfflineSync';
import { enqueueEntry, newEntryKey, entryKeyOf, workDateOf, OP_WITHDRAW } from './offlineQueue';
import { recordOfflineEntry, formatHours, type LineCreatePayload } from './api';

const fieldCls =
  'h-8 w-full rounded-lg border border-border-light bg-surface-primary px-2.5 text-sm text-content-primary';

function joinLabel(...parts: (string | null | undefined)[]): string {
  return parts.filter(Boolean).join(' · ');
}

export interface OfflineDayRecorderProps {
  projectId: string;
  /** Called after an entry reaches the server, so the lists can refresh. */
  onRecorded?: () => void;
}

export function OfflineDayRecorder({ projectId, onRecorded }: OfflineDayRecorderProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { online, pending, syncing, lastSummary, sync, discard } = useFieldTimeOfflineSync();

  const [entryKey, setEntryKey] = useState(() => newEntryKey());
  const [date, setDate] = useState(() => todayLocalISO());
  const [note, setNote] = useState('');
  const [lines, setLines] = useState<LineCreatePayload[]>([]);
  const [sendForApproval, setSendForApproval] = useState(true);
  const [saving, setSaving] = useState(false);

  // The same query keys the editor uses, so whichever surface is opened first
  // warms the pickers for the other - which is how the roster is still there
  // after the link drops.
  // Scoped to the open project. A day sheet is written for one site, and an
  // unscoped roster offered the supervisor crews from every other project on
  // the install. The project id is part of the key so the two field-time
  // surfaces cannot warm each other with another project's roster.
  const resourcesQ = useQuery({
    queryKey: ['resources', 'list', 'field-time', projectId],
    queryFn: () => listResources({ limit: 500, project_id: projectId }),
    // Without a project there is nothing to scope to, and asking anyway is
    // the unscoped roster again. A day cannot be recorded projectless.
    enabled: !!projectId,
  });
  const equipmentQ = useQuery({
    queryKey: ['equipment', 'list', 'field-time'],
    queryFn: () => listEquipment({ limit: 500 }),
  });
  const variationsQ = useQuery({
    queryKey: ['variations', 'requests', projectId, 'field-time'],
    queryFn: () => listVariationRequests({ project_id: projectId, limit: 200 }),
    enabled: !!projectId,
  });

  const labour: PickOption[] = useMemo(
    () =>
      (resourcesQ.data?.items ?? [])
        .filter((r) => r.resource_type !== 'equipment')
        .map((r) => ({ id: r.id, label: joinLabel(r.code, r.name) || r.id })),
    [resourcesQ.data],
  );
  const plant: PickOption[] = useMemo(
    () => (equipmentQ.data?.items ?? []).map((e) => ({ id: e.id, label: joinLabel(e.code, e.name) || e.id })),
    [equipmentQ.data],
  );
  const variations: PickOption[] = useMemo(
    () => (variationsQ.data?.items ?? []).map((v) => ({ id: v.id, label: joinLabel(v.code, v.title) || v.id })),
    [variationsQ.data],
  );

  const totalHours = useMemo(
    () => lines.reduce((sum, l) => sum + (Number(l.hours) || 0), 0),
    [lines],
  );

  const resetComposer = () => {
    // A new key for a new day: reusing it would make the next day read as an
    // edit of the last one and overwrite it.
    setEntryKey(newEntryKey());
    setDate(todayLocalISO());
    setNote('');
    setLines([]);
  };

  const handleSave = async () => {
    if (lines.length === 0 || saving) return;
    const payload = {
      entry_key: entryKey,
      project_id: projectId,
      date,
      note: note.trim() || null,
      lines,
      captured_at: new Date().toISOString(),
      submit: sendForApproval,
    };
    setSaving(true);
    try {
      if (online) {
        const result = await recordOfflineEntry(payload);
        queryClient.invalidateQueries({ queryKey: ['field-time', 'list'] });
        queryClient.invalidateQueries({ queryKey: ['field-time', 'summary'] });
        onRecorded?.();
        addToast({
          type: result.submitted ? 'success' : 'warning',
          title: result.submitted
            ? t('field_time.offline.sent_title', { defaultValue: 'Day sent to the office' })
            : t('field_time.offline.draft_title', { defaultValue: 'Day saved as a draft' }),
          message: result.submitted
            ? undefined
            : t('field_time.offline.draft_hint', {
                defaultValue: 'It needs a correction before it can be sent for approval.',
              }),
        });
      } else {
        await enqueueEntry(payload);
        addToast({
          type: 'info',
          title: t('field_time.offline.queued_title', { defaultValue: 'Day held on this device' }),
          message: t('field_time.offline.queued_hint', {
            defaultValue: 'It will be sent to the office by itself as soon as there is a signal.',
          }),
        });
      }
      resetComposer();
    } catch (e) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <CollapsibleSection
      storageKey="field_time.offline"
      icon={
        online ? (
          <Cloud size={15} className="text-oe-blue" />
        ) : (
          <CloudOff size={15} className="text-amber-500" />
        )
      }
      title={t('field_time.offline.title', { defaultValue: 'Record a day on site' })}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-content-tertiary">
          {online
            ? t('field_time.offline.intro_online', {
                defaultValue:
                  'Book the whole day here and send it in one go. If the signal drops before you finish, the day is kept on this device and sent by itself later.',
              })
            : t('field_time.offline.intro_offline', {
                defaultValue:
                  'No signal. Book the day as usual: it is kept on this device and sent to the office by itself when the link comes back.',
              })}
        </p>
        <ConnectivityBadge online={online} pending={pending.length} />
      </div>

      {pending.length > 0 && (
        <PendingList
          pending={pending}
          syncing={syncing}
          online={online}
          onSync={sync}
          onDiscard={discard}
        />
      )}

      {lastSummary && <SyncSummary summary={lastSummary} />}

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label>
          <span className="mb-1 block text-2xs font-medium text-content-tertiary">
            {t('field_time.offline.work_date', { defaultValue: 'Day worked' })}
          </span>
          <input
            type="date"
            value={date}
            className={fieldCls}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label className="sm:col-span-2">
          <span className="mb-1 block text-2xs font-medium text-content-tertiary">
            {t('field_time.note', { defaultValue: 'Note' })}
          </span>
          <input
            value={note}
            className={fieldCls}
            placeholder={t('field_time.offline.note_placeholder', {
              defaultValue: 'What happened on site, in one line',
            })}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      </div>

      <div className="mt-3">
        <LineComposer
          projectId={projectId}
          labour={labour}
          plant={plant}
          variations={variations}
          onAdd={async (payload) => {
            setLines((prev) => [...prev, payload]);
          }}
        />
      </div>

      {lines.length > 0 && (
        <StagedLines
          lines={lines}
          labour={labour}
          plant={plant}
          onRemove={(index) => setLines((prev) => prev.filter((_, i) => i !== index))}
        />
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border-light pt-3">
        <Toggle
          checked={sendForApproval}
          size="sm"
          onChange={setSendForApproval}
          label={t('field_time.offline.send_for_approval', {
            defaultValue: 'Send for approval straight away',
          })}
        />
        <div className="flex items-center gap-3">
          {/* Two keys the module already ships translated, rather than a new
              counted one: i18next only pluralises a variable literally named
              ``count``, and a fresh counted key would owe every language its
              own CLDR forms. */}
          <span className="text-xs tabular-nums text-content-secondary">
            {t('field_time.lines_count', { defaultValue: '{{count}} lines', count: lines.length })}
            {' · '}
            {t('field_time.hours_value', {
              defaultValue: '{{hours}} h',
              hours: formatHours(String(totalHours)),
            })}
          </span>
          <Button
            variant="primary"
            size="sm"
            icon={<Save size={14} />}
            loading={saving}
            disabled={lines.length === 0}
            onClick={handleSave}
          >
            {online
              ? t('field_time.offline.save_online', { defaultValue: 'Send the day' })
              : t('field_time.offline.save_offline', { defaultValue: 'Keep on this device' })}
          </Button>
        </div>
      </div>
    </CollapsibleSection>
  );
}

function ConnectivityBadge({ online, pending }: { online: boolean; pending: number }) {
  const { t } = useTranslation();
  if (!online) {
    return (
      <Badge variant="warning" size="sm">
        {t('field_time.offline.state_offline', { defaultValue: 'No signal' })}
      </Badge>
    );
  }
  if (pending > 0) {
    return (
      <Badge variant="blue" size="sm">
        {t('field_time.offline.state_pending', {
          defaultValue: 'Waiting to send: {{n}}',
          n: pending,
        })}
      </Badge>
    );
  }
  return (
    <Badge variant="success" size="sm">
      {t('field_time.offline.state_synced', { defaultValue: 'Everything sent' })}
    </Badge>
  );
}

function PendingList({
  pending,
  syncing,
  online,
  onSync,
  onDiscard,
}: {
  pending: QueuedOp[];
  syncing: boolean;
  online: boolean;
  onSync: () => Promise<void>;
  onDiscard: (clientOpId: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-content-primary">
          <Clock size={13} className="text-amber-500" />
          {t('field_time.offline.pending_title', {
            defaultValue: 'Still on this device: {{n}}',
            n: pending.length,
          })}
        </span>
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw size={13} className={syncing ? 'animate-spin' : undefined} />}
          loading={syncing}
          disabled={!online}
          onClick={() => void onSync()}
        >
          {t('field_time.offline.sync_now', { defaultValue: 'Send them now' })}
        </Button>
      </div>
      <ul className="mt-2 flex flex-col gap-1">
        {pending.map((op) => (
          <li
            key={op.clientOpId}
            className="flex items-center gap-2 rounded-md bg-surface-primary px-2.5 py-1.5 text-xs"
          >
            <span className="min-w-0 flex-1 truncate text-content-secondary">
              {op.kind === OP_WITHDRAW
                ? t('field_time.offline.pending_withdraw', { defaultValue: 'Withdrawal of a day' })
                : workDateOf(op) || entryKeyOf(op)}
            </span>
            {op.retries > 0 && (
              <span className="shrink-0 text-2xs text-amber-600">
                {t('field_time.offline.pending_retries', {
                  defaultValue: 'Attempts: {{n}}',
                  n: op.retries,
                })}
              </span>
            )}
            <button
              type="button"
              aria-label={t('field_time.offline.discard', { defaultValue: 'Discard this entry' })}
              className="shrink-0 rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-error"
              onClick={() => void onDiscard(op.clientOpId)}
            >
              <Trash2 size={13} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SyncSummary({
  summary,
}: {
  summary: { applied: number; conflict: number; rejected: number; retry: number };
}) {
  const { t } = useTranslation();
  const refused = summary.conflict + summary.rejected;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2 text-xs">
      {summary.applied > 0 && (
        <span className="inline-flex items-center gap-1.5 text-content-secondary">
          <CheckCircle2 size={13} className="text-success" />
          {t('field_time.offline.summary_applied', {
            defaultValue: 'Reached the office: {{n}}',
            n: summary.applied,
          })}
        </span>
      )}
      {refused > 0 && (
        <span className="inline-flex items-center gap-1.5 text-content-secondary">
          <AlertTriangle size={13} className="text-error" />
          {t('field_time.offline.summary_refused', {
            defaultValue: 'Refused, enter again: {{n}}',
            n: refused,
          })}
        </span>
      )}
      {summary.retry > 0 && (
        <span className="inline-flex items-center gap-1.5 text-content-secondary">
          <Clock size={13} className="text-amber-500" />
          {t('field_time.offline.summary_retry', {
            defaultValue: 'Not sent yet: {{n}}',
            n: summary.retry,
          })}
        </span>
      )}
    </div>
  );
}

function StagedLines({
  lines,
  labour,
  plant,
  onRemove,
}: {
  lines: LineCreatePayload[];
  labour: PickOption[];
  plant: PickOption[];
  onRemove: (index: number) => void;
}) {
  const { t } = useTranslation();
  const nameOf = (line: LineCreatePayload): string => {
    const pool = line.resource_id ? labour : plant;
    const id = line.resource_id ?? line.equipment_id ?? '';
    return pool.find((o) => o.id === id)?.label ?? id;
  };
  return (
    <ul className="mt-2 flex flex-col gap-1">
      {lines.map((line, index) => (
        <li
          key={`${line.resource_id ?? line.equipment_id ?? 'line'}-${index}`}
          className="flex items-center gap-2 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs"
        >
          <span className="min-w-0 flex-1 truncate text-content-primary">{nameOf(line)}</span>
          <span className="shrink-0 tabular-nums text-content-secondary">
            {t('field_time.hours_value', { defaultValue: '{{hours}} h', hours: formatHours(line.hours) })}
          </span>
          <span className="hidden shrink-0 text-content-tertiary sm:inline">{line.cost_code}</span>
          {line.is_daywork && (
            <Badge variant="blue" size="sm">
              {t('field_time.daywork_flag', { defaultValue: 'Daywork' })}
            </Badge>
          )}
          <button
            type="button"
            aria-label={t('field_time.offline.remove_line', { defaultValue: 'Remove this line' })}
            className="shrink-0 rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-error"
            onClick={() => onRemove(index)}
          >
            <Trash2 size={13} />
          </button>
        </li>
      ))}
    </ul>
  );
}
