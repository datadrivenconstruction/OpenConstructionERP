// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RecurringSeriesDialog — create a meeting-minutes-tool-style meeting series.
//
// Mirrors the master-meeting fields from the normal "New Meeting" form,
// plus a small recurrence panel: FREQ (DAILY/WEEKLY/MONTHLY), BYDAY
// (Mon–Sun checkboxes — only shown for WEEKLY), and COUNT.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, WideModal, WideModalSection, WideModalField } from '@/shared/ui';
import {
  buildRRule,
  type CreateSeriesPayload,
  type MeetingType,
  type RecurrenceFreq,
  type WeekdayToken,
  WEEKDAY_TOKENS,
} from './api';

interface RecurringSeriesDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  isPending: boolean;
  onSubmit: (payload: CreateSeriesPayload) => void;
}

const MEETING_TYPES: MeetingType[] = [
  'progress',
  'design',
  'safety',
  'subcontractor',
  'kickoff',
  'closeout',
];

const FREQS: RecurrenceFreq[] = ['DAILY', 'WEEKLY', 'MONTHLY'];

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function RecurringSeriesDialog({
  open,
  onClose,
  projectId,
  isPending,
  onSubmit,
}: RecurringSeriesDialogProps) {
  const { t } = useTranslation();

  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const [title, setTitle] = useState('');
  const [meetingType, setMeetingType] = useState<MeetingType>('progress');
  const [startDate, setStartDate] = useState(todayIso);
  const [location, setLocation] = useState('');

  const [freq, setFreq] = useState<RecurrenceFreq>('WEEKLY');
  const [byday, setByday] = useState<WeekdayToken[]>(['MO']);
  const [count, setCount] = useState<number>(12);
  const [materializeUntil, setMaterializeUntil] = useState('');

  const toggleByday = (token: WeekdayToken) => {
    setByday((prev) =>
      prev.includes(token) ? prev.filter((d) => d !== token) : [...prev, token],
    );
  };

  const canSubmit =
    title.trim().length > 0 && startDate.length === 10 && count >= 1 && !isPending;

  const handleSubmit = () => {
    if (!canSubmit) return;
    const rule = buildRRule({
      freq,
      byday: freq === 'WEEKLY' ? byday : [],
      count,
    });
    onSubmit({
      project_id: projectId,
      title: title.trim(),
      meeting_type: meetingType,
      meeting_date: startDate,
      location: location.trim() || undefined,
      recurrence_rule: rule,
      materialize_until: materializeUntil || undefined,
      status: 'scheduled',
    });
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('meetings.create_series', { defaultValue: 'Create Recurring Series' })}
      subtitle={t('meetings.create_series_hint', {
        defaultValue:
          'Define the master meeting and a recurrence rule. Occurrences are auto-materialised.',
      })}
      size="lg"
      busy={isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!canSubmit}>
            {isPending
              ? t('common.saving', { defaultValue: 'Saving…' })
              : t('meetings.create_series_action', {
                  defaultValue: 'Create Series',
                })}
          </Button>
        </div>
      }
    >
      <WideModalSection
        title={t('meetings.series_master', { defaultValue: 'Master meeting' })}
      >
        <WideModalField
          label={t('meetings.col_title', { defaultValue: 'Title' })}
          required
          span={2}
        >
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={inputCls}
            placeholder={t('meetings.title_placeholder', {
              defaultValue: 'Weekly progress meeting',
            })}
            autoFocus
          />
        </WideModalField>
        <WideModalField
          label={t('meetings.col_type', { defaultValue: 'Type' })}
        >
          <select
            value={meetingType}
            onChange={(e) => setMeetingType(e.target.value as MeetingType)}
            className={inputCls}
          >
            {MEETING_TYPES.map((mt) => (
              <option key={mt} value={mt}>
                {t(`meetings.type_${mt}`, {
                  defaultValue: mt.charAt(0).toUpperCase() + mt.slice(1),
                })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('meetings.start_date', { defaultValue: 'Start date' })} required>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('meetings.col_location', { defaultValue: 'Location' })}
          span={2}
        >
          <input
            type="text"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className={inputCls}
            placeholder={t('meetings.location_placeholder', {
              defaultValue: 'Site trailer / video call link',
            })}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('meetings.recurrence', { defaultValue: 'Recurrence' })}
      >
        <WideModalField label={t('meetings.frequency', { defaultValue: 'Frequency' })}>
          <select
            value={freq}
            onChange={(e) => setFreq(e.target.value as RecurrenceFreq)}
            className={inputCls}
          >
            {FREQS.map((f) => (
              <option key={f} value={f}>
                {t(`meetings.freq_${f}`, {
                  defaultValue: f.charAt(0) + f.slice(1).toLowerCase(),
                })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('meetings.count', { defaultValue: 'Number of occurrences' })}>
          <input
            type="number"
            min={1}
            max={52}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(52, Number(e.target.value) || 1)))}
            className={inputCls}
          />
        </WideModalField>
        {freq === 'WEEKLY' && (
          <WideModalField
            label={t('meetings.byday', { defaultValue: 'Days of week' })}
            span={2}
          >
            <div className="flex flex-wrap gap-1.5">
              {WEEKDAY_TOKENS.map((d) => {
                const active = byday.includes(d);
                return (
                  <button
                    key={d}
                    type="button"
                    onClick={() => toggleByday(d)}
                    className={
                      'h-9 min-w-12 rounded-lg border px-3 text-xs font-medium transition-colors ' +
                      (active
                        ? 'bg-oe-blue text-white border-oe-blue'
                        : 'bg-surface-primary text-content-primary border-border hover:bg-surface-secondary')
                    }
                  >
                    {t(`meetings.day_${d}`, { defaultValue: d })}
                  </button>
                );
              })}
            </div>
          </WideModalField>
        )}
        <WideModalField
          label={t('meetings.materialize_until', { defaultValue: 'Materialise until' })}
          span={2}
        >
          <input
            type="date"
            value={materializeUntil}
            onChange={(e) => setMaterializeUntil(e.target.value)}
            className={inputCls}
          />
          <p className="mt-1 text-xs text-content-tertiary">
            {t('meetings.materialize_until_hint', {
              defaultValue:
                'Optional. Pre-create occurrences up to this date. Leave blank to materialise only the COUNT limit.',
            })}
          </p>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
