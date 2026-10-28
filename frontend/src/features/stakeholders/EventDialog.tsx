// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Recording what actually happened: a planned communication that took place,
// a one-off event, or a correction of either. Who attended, what came out of
// it, and the feedback that was promised to the participants.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/Button';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';

import {
  createEvent,
  localToday,
  recordOccurrence,
  updateEvent,
  type EngagementEvent,
  type EventInput,
  type PlanItem,
  type Stakeholder,
} from './api';
import { FIELD_CLASS, RefusalBox, TickList, useWrite } from './StakeholderBits';
import { itemName, type TFn } from './labels';
import { useCorrespondenceOptions, useMeetingOptions, withStored } from './links';
import { stakeholderName, type Screen } from './screen';

/** What the dialog writes: an occurrence of a plan item, a one-off event, or a change to a recorded one. */
export type EventTarget =
  | { kind: 'record'; item: PlanItem; date: string | null }
  | { kind: 'new' }
  | { kind: 'edit'; event: EngagementEvent };

export interface EventDialogProps {
  screen: Screen;
  target: EventTarget;
  stakeholders: Stakeholder[];
  onClose: () => void;
  onSaved: () => void;
}

export function EventDialog({ screen, target, stakeholders, onClose, onSaved }: EventDialogProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels } = screen;
  const fw = settings.framework;
  const levels = [...fw.participation_levels].sort((a, b) => a.order - b.order);
  const event = target.kind === 'edit' ? target.event : null;
  const item = target.kind === 'record' ? target.item : null;
  const [draft, setDraft] = useState({
    title: event?.title ?? item?.title ?? '',
    held_on: event?.held_on ?? (target.kind === 'edit' ? '' : localToday()),
    location: event?.location ?? '',
    level: event?.participation_level ?? item?.participation_level ?? levels[0]?.code ?? '',
    attendees: event?.stakeholder_ids ?? item?.audience_stakeholder_ids ?? [],
    attendance: event?.attendance_count != null ? String(event.attendance_count) : '',
    outcome: event?.outcome ?? '',
    feedback: event?.feedback_summary ?? '',
    meeting: event?.meeting_id ?? '',
    letters: event?.correspondence_ids ?? [],
  });
  const kept = t('stakeholders.ui.link.kept', { defaultValue: 'Linked record (kept as it is)' });
  const meetings = withStored(useMeetingOptions(projectId, t as TFn).options, draft.meeting, kept);
  const letterOptions = useCorrespondenceOptions(projectId, t as TFn).options;
  // A letter that is linked but no longer listed stays ticked, so a save does not drop it.
  const letters = [
    ...(event?.correspondence_ids ?? []).filter((id) => !letterOptions.some((o) => o.id === id)).map((id) => ({ id, label: kept })),
    ...letterOptions,
  ];
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const write = useWrite((body: EventInput) => {
    if (target.kind === 'record') return recordOccurrence(projectId, target.item.id, body);
    if (target.kind === 'edit') return updateEvent(projectId, target.event.id, body);
    return createEvent(projectId, body);
  }, onSaved);

  const ready = !!draft.title.trim() && (target.kind === 'edit' || !!draft.held_on);

  const submit = () => {
    const body: EventInput = {
      title: draft.title.trim(),
      location: draft.location.trim(),
      stakeholder_ids: draft.attendees,
      attendance_count: draft.attendance ? Number(draft.attendance) : null,
      outcome: draft.outcome.trim(),
      feedback_summary: draft.feedback.trim(),
      meeting_id: draft.meeting || null,
      correspondence_ids: draft.letters,
    };
    if (draft.held_on) body.held_on = draft.held_on;
    if (target.kind === 'record' && target.date) body.occurrence_date = target.date;
    if (target.kind !== 'record') body.participation_level = draft.level || null;
    if (target.kind === 'new') body.status = 'held';
    // Entering the day a planned event took place is what marks it as held.
    if (event && event.status === 'planned' && draft.held_on) body.status = 'held';
    write.run(body);
  };

  const title =
    target.kind === 'record'
      ? t('stakeholders.ui.event.record_title', { defaultValue: 'Record that it took place' })
      : target.kind === 'edit'
        ? t('stakeholders.ui.event.edit_title', { defaultValue: 'Edit recorded event' })
        : t('stakeholders.ui.event.add_title', { defaultValue: 'Record an event' });

  return (
    <WideModal
      open
      onClose={onClose}
      busy={write.busy}
      size="lg"
      testId="event-dialog"
      title={title}
      subtitle={t('stakeholders.ui.event.dialog_subtitle', {
        defaultValue: 'Who took part, what came out of it, and what you reported back to them.',
      })}
      footer={
        <div className="flex w-full items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={write.busy}>
            {t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={write.busy} disabled={!ready} onClick={submit} data-testid="event-save">
            {t('stakeholders.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox refusal={write.refusal} />
        <WideModalSection columns={2}>
          <WideModalField label={t('stakeholders.ui.plan.title', { defaultValue: 'Title' })} required span={2} htmlFor="event-title">
            <input
              id="event-title"
              className={FIELD_CLASS}
              value={draft.title}
              maxLength={255}
              onChange={(e) => set('title', e.target.value)}
            />
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.event.held_on', { defaultValue: 'Day it took place' })}
            required={target.kind !== 'edit'}
            htmlFor="event-held"
          >
            <input
              id="event-held"
              type="date"
              className={FIELD_CLASS}
              value={draft.held_on}
              onChange={(e) => set('held_on', e.target.value)}
            />
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.event.location', { defaultValue: 'Place' })} htmlFor="event-location">
            <input
              id="event-location"
              className={FIELD_CLASS}
              value={draft.location}
              maxLength={255}
              onChange={(e) => set('location', e.target.value)}
            />
          </WideModalField>
          {target.kind !== 'record' && (
            <WideModalField label={t('stakeholders.ui.plan.level', { defaultValue: 'How far they take part' })} htmlFor="event-level">
              <select id="event-level" className={FIELD_CLASS} value={draft.level} onChange={(e) => set('level', e.target.value)}>
                {levels.map((l) => (
                  <option key={l.code} value={l.code}>
                    {itemName(labels, l)}
                  </option>
                ))}
              </select>
            </WideModalField>
          )}
          <WideModalField
            label={t('stakeholders.ui.event.attendance', { defaultValue: 'Number of people present' })}
            htmlFor="event-attendance"
          >
            <input
              id="event-attendance"
              type="number"
              min={0}
              className={FIELD_CLASS}
              value={draft.attendance}
              onChange={(e) => set('attendance', e.target.value)}
            />
          </WideModalField>
        </WideModalSection>

        <WideModalField label={t('stakeholders.ui.event.attendees', { defaultValue: 'Stakeholders who took part' })}>
          <TickList
            testId="event-attendees"
            label={t('stakeholders.ui.event.attendees', { defaultValue: 'Stakeholders who took part' })}
            emptyText={t('stakeholders.ui.plan.no_stakeholders', { defaultValue: 'The register has no stakeholders yet.' })}
            options={stakeholders
              .filter((s) => s.status !== 'archived' || draft.attendees.includes(s.id))
              .map((s) => ({ id: s.id, label: stakeholderName(t, s) }))}
            value={draft.attendees}
            onChange={(next) => set('attendees', next)}
          />
        </WideModalField>

        <WideModalSection title={t('stakeholders.ui.link.title', { defaultValue: 'On record elsewhere in the project' })} columns={2}>
          <WideModalField label={t('stakeholders.ui.link.meeting', { defaultValue: 'The meeting it was' })} htmlFor="event-meeting">
            <select id="event-meeting" className={FIELD_CLASS} value={draft.meeting} onChange={(e) => set('meeting', e.target.value)}>
              <option value="">{t('stakeholders.ui.link.no_meeting', { defaultValue: 'Not a recorded meeting' })}</option>
              {meetings.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.link.letters', { defaultValue: 'Letters that belong to it' })}>
            <TickList
              testId="event-letters"
              label={t('stakeholders.ui.link.letters', { defaultValue: 'Letters that belong to it' })}
              emptyText={t('stakeholders.ui.link.no_letters', { defaultValue: 'The project has no letters on record.' })}
              options={letters}
              value={draft.letters}
              onChange={(next) => set('letters', next)}
            />
          </WideModalField>
        </WideModalSection>

        <WideModalSection columns={1}>
          <WideModalField label={t('stakeholders.ui.event.outcome', { defaultValue: 'What came out of it' })} htmlFor="event-outcome">
            <textarea
              id="event-outcome"
              rows={3}
              className={FIELD_CLASS}
              value={draft.outcome}
              onChange={(e) => set('outcome', e.target.value)}
            />
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.event.feedback', { defaultValue: 'What you reported back to the participants' })}
            hint={t('stakeholders.ui.event.feedback_hint', {
              defaultValue: 'When people were consulted, they are owed an answer on what their input changed. Leave empty until you have told them.',
            })}
            htmlFor="event-feedback"
          >
            <textarea
              id="event-feedback"
              rows={3}
              className={FIELD_CLASS}
              value={draft.feedback}
              onChange={(e) => set('feedback', e.target.value)}
            />
          </WideModalField>
        </WideModalSection>
      </div>
    </WideModal>
  );
}
