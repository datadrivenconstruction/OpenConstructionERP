// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Edit a logged call. Mirrors the manual capture form and saves through the
// same PATCH the recording review uses (finalizePhoneLog). The stored protocol
// (decisions, action items) is preserved by NOT sending a protocol payload, and
// the existing instructions are carried through so an edit never silently drops
// them; the server re-normalizes parties, direction, channel, and duration.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Loader2, Save } from 'lucide-react';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { finalizePhoneLog } from './api';
import { CHANNELS, DIRECTIONS, channelLabel, directionLabel } from './labels';
import type { PhoneChannel, PhoneDirection, PhoneLog } from './types';

const CONTROL =
  'rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary';

const DIRECTION_SET: PhoneDirection[] = ['inbound', 'outbound', 'internal', 'unknown'];
const CHANNEL_SET: PhoneChannel[] = ['phone', 'voice_note', 'chat', 'other'];

function isDirection(v: string): v is PhoneDirection {
  return (DIRECTION_SET as string[]).includes(v);
}
function isChannel(v: string): v is PhoneChannel {
  return (CHANNEL_SET as string[]).includes(v);
}

// duration_seconds is an integer count (not a Decimal string), so deriving a
// minutes value for the input is safe. Round to 2 dp so a whole/half-minute
// call round-trips exactly (90s -> 1.5 -> 90s).
function secondsToMinutes(sec: number | null): string {
  if (sec == null || sec <= 0) return '';
  return String(Math.round((sec / 60) * 100) / 100);
}

interface EditState {
  raw_parties: string;
  direction: PhoneDirection;
  channel: PhoneChannel;
  started_at: string;
  duration_minutes: string;
  summary: string;
  transcript: string;
}

function initialState(log: PhoneLog): EditState {
  return {
    raw_parties: log.parties.join(', '),
    direction: isDirection(log.direction) ? log.direction : 'inbound',
    channel: isChannel(log.channel) ? log.channel : 'phone',
    started_at: (log.occurred_at || '').slice(0, 16),
    duration_minutes: secondsToMinutes(log.duration_seconds),
    summary: log.summary,
    transcript: log.transcript,
  };
}

export function PhoneLogEditDialog({
  log,
  open,
  onClose,
  onSaved,
}: {
  log: PhoneLog;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<EditState>(() => initialState(log));

  const set = <K extends keyof EditState>(key: K, value: EditState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const saveMutation = useMutation({
    mutationFn: () => {
      const minutes = parseFloat(form.duration_minutes);
      return finalizePhoneLog(log.id, {
        direction: form.direction,
        channel: form.channel,
        raw_parties: form.raw_parties,
        occurred_at: form.started_at || null,
        duration_seconds: Number.isFinite(minutes) && minutes > 0 ? Math.round(minutes * 60) : null,
        transcript: form.transcript,
        summary: form.summary,
        instructions: log.instructions,
      });
    },
    onSuccess: () => {
      addToast({ type: 'success', title: t('phonelog.edit_saved', { defaultValue: 'Call updated' }) });
      onSaved();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('phonelog.edit_error', { defaultValue: 'Could not update the call' }),
        message: getErrorMessage(err),
      });
    },
  });

  const canSave = form.transcript.trim() !== '' || form.summary.trim() !== '';

  // A call stored with a non-canonical direction / channel keeps it selectable.
  const directionOptions = DIRECTIONS.includes(form.direction)
    ? DIRECTIONS
    : [...DIRECTIONS, form.direction];
  const channelOptions = CHANNELS.includes(form.channel) ? CHANNELS : [...CHANNELS, form.channel];

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={saveMutation.isPending}
      size="lg"
      title={t('phonelog.edit_title', { defaultValue: 'Edit call' })}
      subtitle={t('phonelog.edit_subtitle', {
        defaultValue: 'Correct the details of this logged call. The transcript is kept as the underlying evidence.',
      })}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={saveMutation.isPending}
            className="rounded-md border border-border-light px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={!canSave || saveMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {t('phonelog.save_changes', { defaultValue: 'Save changes' })}
          </button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('phonelog.parties', { defaultValue: 'Parties' })} span={2}>
          <input
            value={form.raw_parties}
            onChange={(e) => set('raw_parties', e.target.value)}
            placeholder={t('phonelog.parties_ph', { defaultValue: 'You -> Acme site office' })}
            className={CONTROL}
          />
        </WideModalField>

        <WideModalField label={t('phonelog.when', { defaultValue: 'When' })}>
          <input
            type="datetime-local"
            value={form.started_at}
            onChange={(e) => set('started_at', e.target.value)}
            className={CONTROL}
          />
        </WideModalField>

        <WideModalField label={t('phonelog.duration_min', { defaultValue: 'Duration (minutes)' })}>
          <input
            type="number"
            min="0"
            step="1"
            value={form.duration_minutes}
            onChange={(e) => set('duration_minutes', e.target.value)}
            className={CONTROL}
          />
        </WideModalField>

        <WideModalField label={t('phonelog.direction', { defaultValue: 'Direction' })}>
          <select
            value={form.direction}
            onChange={(e) => set('direction', e.target.value as PhoneDirection)}
            className={CONTROL}
          >
            {directionOptions.map((d) => (
              <option key={d} value={d}>
                {directionLabel(t, d)}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField label={t('phonelog.channel', { defaultValue: 'Channel' })}>
          <select
            value={form.channel}
            onChange={(e) => set('channel', e.target.value as PhoneChannel)}
            className={CONTROL}
          >
            {channelOptions.map((c) => (
              <option key={c} value={c}>
                {channelLabel(t, c)}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField label={t('phonelog.summary', { defaultValue: 'Summary (optional)' })} span={2}>
          <input
            value={form.summary}
            onChange={(e) => set('summary', e.target.value)}
            placeholder={t('phonelog.summary_ph', { defaultValue: 'Agreed to revise the slab pour date' })}
            className={CONTROL}
          />
        </WideModalField>

        <WideModalField label={t('phonelog.transcript', { defaultValue: 'What was said' })} span={2}>
          <textarea
            value={form.transcript}
            onChange={(e) => set('transcript', e.target.value)}
            rows={5}
            className={CONTROL}
          />
        </WideModalField>
      </WideModalSection>

      {saveMutation.isError && (
        <p className="text-sm text-red-600">{getErrorMessage(saveMutation.error)}</p>
      )}
    </WideModal>
  );
}
