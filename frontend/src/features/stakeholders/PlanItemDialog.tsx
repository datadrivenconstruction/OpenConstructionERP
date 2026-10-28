// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One line of the communication plan: what is said, to whom, how deeply they
// take part, through which channel, how often and who is responsible. The
// audience is named stakeholders, whole categories, or both.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/Button';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';

import { createPlanItem, updatePlanItem, type PlanItem, type PlanItemInput, type PlanStatus, type Stakeholder } from './api';
import { FIELD_CLASS, RefusalBox, TickList, useWrite } from './StakeholderBits';
import { PLAN_STATUS, itemName, vocab } from './labels';
import { useGateOptions } from './links';
import {
  FREQUENCY,
  FREQUENCY_RULE,
  PLAN_START,
  planStartOf,
  planStatusOptions,
  presetOfFrequency,
  triggerOf,
  type FrequencyPreset,
  type PlanStart,
} from './rules';
import { stakeholderName, type Screen } from './screen';

export interface PlanItemDialogProps {
  screen: Screen;
  item: PlanItem | null;
  stakeholders: Stakeholder[];
  onClose: () => void;
  onSaved: () => void;
}

export function PlanItemDialog({ screen, item, stakeholders, onClose, onSaved }: PlanItemDialogProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels, personName } = screen;
  const fw = settings.framework;
  const levels = [...fw.participation_levels].sort((a, b) => a.order - b.order);
  const storedPreset = presetOfFrequency(item?.frequency);
  // Null for a trigger this screen does not offer: it is shown as kept and not sent.
  const storedStart = planStartOf(item);
  const storedGate = item?.trigger_kind === 'gate' ? (item.trigger_ref ?? '') : '';
  const gateChoices = useGateOptions(projectId);
  const gates = gateChoices.options;
  // A project run without gates: the server refuses a line that waits for one, so it is not offered.
  // A line that already waits for a gate keeps showing it, with the reason it will never start.
  const gatesOff = !gateChoices.inUse;
  // Which starts need a gate is the server's list: the gate itself and the events only a gate causes.
  const needsGates = (start: string) => start === 'gate' || gateChoices.gateBound.includes(start);
  const [draft, setDraft] = useState({
    title: item?.title ?? '',
    purpose: item?.purpose ?? '',
    key_message: item?.key_message ?? '',
    audience: item?.audience_stakeholder_ids ?? [],
    categories: item?.audience_categories ?? [],
    level: item?.participation_level ?? levels[0]?.code ?? '',
    channel: item?.channel ?? fw.channels[0]?.code ?? '',
    format: item?.format_code ?? '',
    // A rule written some other way is kept as it is unless the reader picks a preset.
    frequency: (storedPreset ?? 'custom') as FrequencyPreset | 'custom',
    start: (storedStart ?? 'kept') as PlanStart | 'kept',
    // Empty means every gate of the project.
    gate: storedGate,
    starts_on: item?.starts_on ?? '',
    ends_on: item?.ends_on ?? '',
    owner: item?.owner_user_id ?? '',
    status: (item?.status ?? 'active') as PlanStatus,
  });
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const write = useWrite(
    (body: PlanItemInput) => (item ? updatePlanItem(projectId, item.id, body) : createPlanItem(projectId, body)),
    onSaved,
  );

  const triggered = draft.start !== 'schedule';
  const audienceMissing = draft.audience.length === 0 && draft.categories.length === 0 && !item?.audience_body_id;
  const ready = !!draft.title.trim() && !audienceMissing && (triggered || !!draft.starts_on);

  const submit = () => {
    const body: PlanItemInput = {
      title: draft.title.trim(),
      purpose: draft.purpose.trim(),
      key_message: draft.key_message.trim(),
      audience_stakeholder_ids: draft.audience,
      audience_categories: draft.categories,
      participation_level: draft.level,
      channel: draft.channel,
      format_code: draft.format || null,
      owner_user_id: draft.owner || null,
      status: draft.status,
    };
    if (!triggered && draft.frequency !== 'custom') body.frequency = FREQUENCY_RULE[draft.frequency];
    const gateChanged = draft.start === 'gate' && draft.gate !== storedGate;
    if (draft.start !== 'kept' && (draft.start !== storedStart || gateChanged)) {
      Object.assign(body, triggerOf(draft.start, draft.gate));
    }
    if (!triggered || draft.starts_on) body.starts_on = draft.starts_on || null;
    body.ends_on = draft.ends_on || null;
    write.run(body);
  };

  const level = levels.find((l) => l.code === draft.level);
  const promise = level?.promise_key && labels.exists(level.promise_key) ? labels.t(level.promise_key) : '';

  return (
    <WideModal
      open
      onClose={onClose}
      busy={write.busy}
      size="xl"
      testId="plan-item-dialog"
      title={
        item
          ? t('stakeholders.ui.plan.edit_title', { defaultValue: 'Edit planned communication' })
          : t('stakeholders.ui.plan.add_title', { defaultValue: 'Plan a communication' })
      }
      subtitle={t('stakeholders.ui.plan.dialog_subtitle', {
        defaultValue: 'What you tell or ask, whom, how often, and who on the team is responsible.',
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {audienceMissing && (
            <p className="mr-auto text-xs text-semantic-error" data-testid="plan-audience-missing">
              {t('stakeholders.ui.plan.audience_missing', {
                defaultValue: 'Choose at least one stakeholder or one category as the audience.',
              })}
            </p>
          )}
          <Button variant="ghost" onClick={onClose} disabled={write.busy}>
            {t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={write.busy} disabled={!ready} onClick={submit} data-testid="plan-item-save">
            {t('stakeholders.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox refusal={write.refusal} />
        <WideModalSection columns={2}>
          <WideModalField label={t('stakeholders.ui.plan.title', { defaultValue: 'Title' })} required span={2} htmlFor="plan-title">
            <input
              id="plan-title"
              className={FIELD_CLASS}
              value={draft.title}
              maxLength={255}
              onChange={(e) => set('title', e.target.value)}
            />
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.plan.purpose', { defaultValue: 'Why this communication' })} htmlFor="plan-purpose">
            <textarea
              id="plan-purpose"
              rows={2}
              className={FIELD_CLASS}
              value={draft.purpose}
              onChange={(e) => set('purpose', e.target.value)}
            />
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.plan.key_message', { defaultValue: 'Key message' })} htmlFor="plan-message">
            <textarea
              id="plan-message"
              rows={2}
              className={FIELD_CLASS}
              value={draft.key_message}
              onChange={(e) => set('key_message', e.target.value)}
            />
          </WideModalField>
        </WideModalSection>

        <WideModalSection title={t('stakeholders.ui.plan.audience', { defaultValue: 'Audience' })} columns={2}>
          <WideModalField label={t('stakeholders.ui.plan.audience_stakeholders', { defaultValue: 'Named stakeholders' })}>
            <TickList
              testId="plan-audience"
              label={t('stakeholders.ui.plan.audience_stakeholders', { defaultValue: 'Named stakeholders' })}
              emptyText={t('stakeholders.ui.plan.no_stakeholders', { defaultValue: 'The register has no stakeholders yet.' })}
              options={stakeholders
                .filter((s) => s.status !== 'archived')
                .map((s) => ({ id: s.id, label: stakeholderName(t, s) }))}
              value={draft.audience}
              onChange={(next) => set('audience', next)}
            />
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.plan.audience_categories', { defaultValue: 'Whole categories' })}>
            <TickList
              label={t('stakeholders.ui.plan.audience_categories', { defaultValue: 'Whole categories' })}
              emptyText=""
              options={fw.stakeholder_categories.map((c) => ({ id: c.code, label: itemName(labels, c) }))}
              value={draft.categories}
              onChange={(next) => set('categories', next)}
            />
          </WideModalField>
        </WideModalSection>

        <WideModalSection title={t('stakeholders.ui.plan.how', { defaultValue: 'How and when' })} columns={3}>
          <WideModalField
            label={t('stakeholders.ui.plan.level', { defaultValue: 'How far they take part' })}
            hint={promise}
            htmlFor="plan-level"
          >
            <select id="plan-level" className={FIELD_CLASS} value={draft.level} onChange={(e) => set('level', e.target.value)}>
              {levels.map((l) => (
                <option key={l.code} value={l.code}>
                  {itemName(labels, l)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.plan.channel', { defaultValue: 'Channel' })} htmlFor="plan-channel">
            <select
              id="plan-channel"
              className={FIELD_CLASS}
              value={draft.channel}
              onChange={(e) => set('channel', e.target.value)}
            >
              {fw.channels.map((c) => (
                <option key={c.code} value={c.code}>
                  {itemName(labels, c)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.plan.format', { defaultValue: 'Format' })} htmlFor="plan-format">
            <select id="plan-format" className={FIELD_CLASS} value={draft.format} onChange={(e) => set('format', e.target.value)}>
              <option value="">{t('stakeholders.ui.plan.format_none', { defaultValue: 'No set format' })}</option>
              {fw.participation_formats.map((f) => (
                <option key={f.code} value={f.code}>
                  {itemName(labels, f)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.plan.start', { defaultValue: 'What sets it off' })}
            error={
              gatesOff && draft.start !== 'gate' && needsGates(draft.start)
                ? t('stakeholders.ui.plan.gates_off_stored', {
                    defaultValue: 'This project does not use gates, so nothing sets this line off. Give it fixed dates instead.',
                  })
                : undefined
            }
            hint={
              gatesOff && !needsGates(draft.start)
                ? t('stakeholders.ui.plan.gates_off', {
                    defaultValue: 'This project does not use gates, so a gate cannot set a line off.',
                  })
                : triggered
                  ? t('stakeholders.ui.plan.triggered_hint', {
                      defaultValue: 'This item is started by a project event, so it needs no first date.',
                    })
                  : undefined
            }
            htmlFor="plan-start"
          >
            <select
              id="plan-start"
              className={FIELD_CLASS}
              value={draft.start}
              onChange={(e) => set('start', e.target.value as PlanStart)}
            >
              {storedStart === null && (
                <option value="kept">{t('stakeholders.ui.start.kept', { defaultValue: 'Another project event (kept as it is)' })}</option>
              )}
              {(Object.keys(PLAN_START) as PlanStart[])
                .filter((s) => !gatesOff || !needsGates(s) || draft.start === s || storedStart === s)
                .map((s) => (
                <option key={s} value={s}>
                  {vocab(t, PLAN_START, s)}
                </option>
              ))}
            </select>
          </WideModalField>
          {draft.start === 'gate' && (
            <WideModalField
              label={t('stakeholders.ui.plan.gate', { defaultValue: 'Which gate' })}
              hint={
                !gatesOff && gates.length === 0
                  ? t('stakeholders.ui.plan.gate_none', {
                      defaultValue: 'This project has no phase model yet, so there are no gates to choose from.',
                    })
                  : undefined
              }
              error={
                gatesOff
                  ? t('stakeholders.ui.plan.gates_off_stored', {
                      defaultValue: 'This project does not use gates, so nothing sets this line off. Give it fixed dates instead.',
                    })
                  : undefined
              }
              htmlFor="plan-gate"
            >
              <select id="plan-gate" className={FIELD_CLASS} value={draft.gate} onChange={(e) => set('gate', e.target.value)}>
                <option value="">{t('stakeholders.ui.plan.gate_every', { defaultValue: 'Every gate' })}</option>
                {draft.gate && !gates.some((g) => g.id === draft.gate) && <option value={draft.gate}>{draft.gate}</option>}
                {gates.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.label}
                  </option>
                ))}
              </select>
            </WideModalField>
          )}
          {!triggered && (
          <WideModalField label={t('stakeholders.ui.plan.frequency', { defaultValue: 'How often' })} htmlFor="plan-frequency">
            <select
              id="plan-frequency"
              className={FIELD_CLASS}
              value={draft.frequency}
              onChange={(e) => set('frequency', e.target.value as FrequencyPreset | 'custom')}
            >
              {storedPreset === null && (
                <option value="custom">{t('stakeholders.ui.frequency.custom', { defaultValue: 'Own schedule (kept as it is)' })}</option>
              )}
              {(Object.keys(FREQUENCY) as FrequencyPreset[]).map((f) => (
                <option key={f} value={f}>
                  {vocab(t, FREQUENCY, f)}
                </option>
              ))}
            </select>
          </WideModalField>
          )}
          {!triggered && (
          <WideModalField label={t('stakeholders.ui.plan.starts_on', { defaultValue: 'First date' })} required htmlFor="plan-starts">
            <input
              id="plan-starts"
              type="date"
              className={FIELD_CLASS}
              value={draft.starts_on}
              onChange={(e) => set('starts_on', e.target.value)}
            />
          </WideModalField>
          )}
          <WideModalField label={t('stakeholders.ui.plan.ends_on', { defaultValue: 'Last date' })} htmlFor="plan-ends">
            <input
              id="plan-ends"
              type="date"
              className={FIELD_CLASS}
              value={draft.ends_on}
              min={draft.starts_on || undefined}
              onChange={(e) => set('ends_on', e.target.value)}
            />
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.plan.owner', { defaultValue: 'Responsible' })}>
            <ProjectPeopleSelect
              projectId={projectId}
              value={draft.owner}
              displayValue={personName(draft.owner) ?? ''}
              onChange={(id) => set('owner', id)}
            />
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.plan.status', { defaultValue: 'Status' })} htmlFor="plan-status">
            <select
              id="plan-status"
              className={FIELD_CLASS}
              value={draft.status}
              onChange={(e) => set('status', e.target.value as PlanStatus)}
            >
              {planStatusOptions(item?.status ?? null).map((s) => (
                <option key={s} value={s}>
                  {vocab(t, PLAN_STATUS, s)}
                </option>
              ))}
            </select>
          </WideModalField>
        </WideModalSection>
      </div>
    </WideModal>
  );
}
