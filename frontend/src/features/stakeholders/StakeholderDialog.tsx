// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Adding a stakeholder to the register, or editing one. A stakeholder is
// either a contact from the address book or a named group (the neighbours of
// a street, a works council); the category comes from the pinned framework.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/Button';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';

import { createStakeholder, updateStakeholder, type Stakeholder, type StakeholderInput } from './api';
import { FIELD_CLASS, LinkSelect, RefusalBox, useWrite } from './StakeholderBits';
import { STAKEHOLDER_STATUS, itemName, vocab, type TFn } from './labels';
import { useRiskOptions } from './links';
import { placeDraftOf, placeOf, placeProblem, samePlace, withDescendants } from './rules';
import { stakeholderName, type Screen } from './screen';

export interface StakeholderDialogProps {
  screen: Screen;
  /** The stakeholder to edit, or null to add one. */
  stakeholder: Stakeholder | null;
  /** The register, to pick the group or organisation this one belongs to. */
  stakeholders: Stakeholder[];
  onClose: () => void;
  onSaved: (saved: Stakeholder) => void;
}

export function StakeholderDialog({ screen, stakeholder, stakeholders, onClose, onSaved }: StakeholderDialogProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels, personName } = screen;
  const fw = settings.framework;
  const [draft, setDraft] = useState({
    display_name: stakeholder?.display_name ?? '',
    category: stakeholder?.category ?? '',
    contact_id: stakeholder?.contact_id ?? '',
    is_group: stakeholder?.is_group ?? false,
    group_size: stakeholder?.group_size_estimate != null ? String(stakeholder.group_size_estimate) : '',
    interests: stakeholder?.interests ?? '',
    expectations: stakeholder?.expectations ?? '',
    concerns: stakeholder?.concerns ?? '',
    owner: stakeholder?.relationship_owner_user_id ?? '',
    is_confidential: stakeholder?.is_confidential ?? false,
    status: stakeholder?.status ?? 'active',
    parent: stakeholder?.parent_stakeholder_id ?? '',
    risk: stakeholder?.risk_id ?? '',
  });
  const [place, setPlace] = useState(() => placeDraftOf(stakeholder?.geo));
  // A private person the reader may not name arrives without the name and
  // without the place. Sending the empty fields back would erase what is
  // stored, so both are left out.
  const masked = !!stakeholder?.masked;
  const placeWrong = masked ? null : placeProblem(place);
  const risks = useRiskOptions(projectId, t as TFn).options;
  const below = stakeholder ? withDescendants(stakeholders, stakeholder.id) : new Set<string>();
  const parents = stakeholders
    .filter((s) => !below.has(s.id) && (s.status !== 'archived' || s.id === draft.parent))
    .map((s) => ({ id: s.id, label: stakeholderName(t, s) }));
  const [confidentialTouched, setConfidentialTouched] = useState(false);
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const write = useWrite((body: StakeholderInput) => {
    return stakeholder ? updateStakeholder(projectId, stakeholder.id, body) : createStakeholder(projectId, body);
  }, onSaved);

  const nameMissing = !masked && !draft.display_name.trim() && !draft.contact_id;
  const ready = !!draft.category && !nameMissing && !placeWrong;

  const submit = () => {
    const body: StakeholderInput = {
      category: draft.category,
      contact_id: draft.contact_id || null,
      is_group: draft.is_group,
      group_size_estimate: draft.is_group && draft.group_size ? Number(draft.group_size) : null,
      interests: draft.interests.trim(),
      expectations: draft.expectations.trim(),
      concerns: draft.concerns.trim(),
      relationship_owner_user_id: draft.owner || null,
    };
    // Left alone, the server marks private persons confidential by their category.
    if (stakeholder || confidentialTouched) body.is_confidential = draft.is_confidential;
    if (stakeholder) body.status = draft.status;
    if (!masked) {
      body.display_name = draft.display_name.trim();
      const next = placeOf(place);
      if (!samePlace(next, stakeholder?.geo ?? null)) body.geo = next;
    }
    if ((draft.parent || null) !== (stakeholder?.parent_stakeholder_id ?? null)) body.parent_stakeholder_id = draft.parent || null;
    if ((draft.risk || null) !== (stakeholder?.risk_id ?? null)) body.risk_id = draft.risk || null;
    write.run(body);
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={write.busy}
      size="lg"
      testId="stakeholder-dialog"
      title={
        stakeholder
          ? t('stakeholders.ui.stakeholder.edit_title', { defaultValue: 'Edit stakeholder' })
          : t('stakeholders.ui.stakeholder.add_title', { defaultValue: 'Add stakeholder' })
      }
      subtitle={t('stakeholders.ui.stakeholder.dialog_subtitle', {
        defaultValue: 'Anyone who is affected by the project or can affect it: a person, an organisation or a group.',
      })}
      footer={
        <div className="flex w-full items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={write.busy}>
            {t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={write.busy} disabled={!ready} onClick={submit} data-testid="stakeholder-save">
            {t('stakeholders.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox refusal={write.refusal} />
        <WideModalSection columns={2}>
          <WideModalField
            label={t('stakeholders.ui.stakeholder.name', { defaultValue: 'Name' })}
            hint={
              masked
                ? t('stakeholders.ui.stakeholder.name_hidden_hint', {
                    defaultValue: 'The name is hidden from you and stays as it is.',
                  })
                : t('stakeholders.ui.stakeholder.name_hint', { defaultValue: 'Required unless you pick a contact below.' })
            }
            htmlFor="stakeholder-name"
          >
            <input
              id="stakeholder-name"
              className={FIELD_CLASS}
              value={draft.display_name}
              maxLength={255}
              disabled={masked}
              onChange={(e) => set('display_name', e.target.value)}
            />
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.stakeholder.category', { defaultValue: 'Category' })}
            required
            htmlFor="stakeholder-category"
          >
            <select
              id="stakeholder-category"
              className={FIELD_CLASS}
              value={draft.category}
              onChange={(e) => set('category', e.target.value)}
            >
              <option value="">{t('stakeholders.ui.choose', { defaultValue: 'Choose' })}</option>
              {fw.stakeholder_categories.map((c) => (
                <option key={c.code} value={c.code}>
                  {itemName(labels, c)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.stakeholder.contact', { defaultValue: 'Contact from the address book' })}
            hint={t('stakeholders.ui.stakeholder.contact_hint', {
              defaultValue: 'Optional. The name then follows the contact.',
            })}
          >
            <ContactSearchInput
              value={draft.contact_id}
              displayValue={stakeholder?.contact_id ? (stakeholder.name ?? '') : ''}
              onChange={(id) => set('contact_id', id)}
              showBrowse={false}
            />
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.stakeholder.owner', { defaultValue: 'Who keeps the relationship' })}
            hint={t('stakeholders.ui.stakeholder.owner_hint', {
              defaultValue: 'The person on the project team this stakeholder talks to.',
            })}
          >
            <ProjectPeopleSelect
              projectId={projectId}
              value={draft.owner}
              displayValue={personName(draft.owner) ?? ''}
              onChange={(id) => set('owner', id)}
            />
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.stakeholder.parent', { defaultValue: 'Belongs to' })}
            hint={t('stakeholders.ui.stakeholder.parent_hint', {
              defaultValue: 'Optional. The group or organisation this stakeholder is part of.',
            })}
            htmlFor="stakeholder-parent"
          >
            <LinkSelect
              id="stakeholder-parent"
              value={draft.parent}
              onChange={(id) => set('parent', id)}
              options={parents}
              emptyText={t('stakeholders.ui.stakeholder.parent_none', { defaultValue: 'The register has nobody else yet.' })}
            />
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.stakeholder.risk', { defaultValue: 'Risk in the risk register' })}
            hint={t('stakeholders.ui.stakeholder.risk_hint', {
              defaultValue: 'Optional. The risk this stakeholder stands for, if the project tracks one.',
            })}
            htmlFor="stakeholder-risk"
          >
            <LinkSelect
              id="stakeholder-risk"
              value={draft.risk}
              onChange={(id) => set('risk', id)}
              options={risks}
              emptyText={t('stakeholders.ui.link.no_risks', { defaultValue: 'The risk register of this project is empty.' })}
            />
          </WideModalField>
        </WideModalSection>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <label className="flex items-center gap-2 text-sm text-content-primary">
            <input type="checkbox" checked={draft.is_group} onChange={(e) => set('is_group', e.target.checked)} />
            {t('stakeholders.ui.stakeholder.is_group', { defaultValue: 'This is a group of people' })}
          </label>
          {draft.is_group && (
            <label className="flex items-center gap-2 text-sm text-content-secondary">
              {t('stakeholders.ui.stakeholder.group_size', { defaultValue: 'About how many' })}
              <input
                type="number"
                min={0}
                className={`${FIELD_CLASS} w-24`}
                value={draft.group_size}
                onChange={(e) => set('group_size', e.target.value)}
              />
            </label>
          )}
          <label className="flex items-center gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              checked={draft.is_confidential}
              onChange={(e) => {
                setConfidentialTouched(true);
                set('is_confidential', e.target.checked);
              }}
            />
            {t('stakeholders.ui.stakeholder.confidential', {
              defaultValue: 'Private person: show the name only to people allowed to see personal data',
            })}
          </label>
        </div>

        {!masked && (
          <WideModalSection
            columns={2}
            title={t('stakeholders.ui.stakeholder.place', { defaultValue: 'Where they are' })}
          >
            <WideModalField
              label={t('stakeholders.ui.stakeholder.address', { defaultValue: 'Address' })}
              hint={t('stakeholders.ui.stakeholder.place_hint', {
                defaultValue: 'Optional. Useful for neighbours and anyone affected by where the site is.',
              })}
              htmlFor="stakeholder-address"
            >
              <input
                id="stakeholder-address"
                className={FIELD_CLASS}
                value={place.address}
                maxLength={255}
                onChange={(e) => setPlace((p) => ({ ...p, address: e.target.value }))}
              />
            </WideModalField>
            <WideModalField
              label={t('stakeholders.ui.stakeholder.parcel', { defaultValue: 'Land parcel' })}
              hint={t('stakeholders.ui.stakeholder.parcel_hint', { defaultValue: 'The parcel number from the land register, if known.' })}
              htmlFor="stakeholder-parcel"
            >
              <input
                id="stakeholder-parcel"
                className={FIELD_CLASS}
                value={place.parcel_ref}
                maxLength={255}
                onChange={(e) => setPlace((p) => ({ ...p, parcel_ref: e.target.value }))}
              />
            </WideModalField>
            <WideModalField
              label={t('stakeholders.ui.stakeholder.lat', { defaultValue: 'Latitude' })}
              hint={t('stakeholders.ui.stakeholder.lat_hint', { defaultValue: 'In degrees with a decimal point, between -90 and 90.' })}
              error={
                placeWrong === 'lat'
                  ? t('stakeholders.ui.stakeholder.lat_wrong', { defaultValue: 'Enter a number between -90 and 90, with a point.' })
                  : undefined
              }
              htmlFor="stakeholder-lat"
            >
              <input
                id="stakeholder-lat"
                inputMode="decimal"
                className={FIELD_CLASS}
                value={place.lat}
                onChange={(e) => setPlace((p) => ({ ...p, lat: e.target.value }))}
              />
            </WideModalField>
            <WideModalField
              label={t('stakeholders.ui.stakeholder.lon', { defaultValue: 'Longitude' })}
              hint={t('stakeholders.ui.stakeholder.lon_hint', { defaultValue: 'In degrees with a decimal point, between -180 and 180.' })}
              error={
                placeWrong === 'lon'
                  ? t('stakeholders.ui.stakeholder.lon_wrong', { defaultValue: 'Enter a number between -180 and 180, with a point.' })
                  : undefined
              }
              htmlFor="stakeholder-lon"
            >
              <input
                id="stakeholder-lon"
                inputMode="decimal"
                className={FIELD_CLASS}
                value={place.lon}
                onChange={(e) => setPlace((p) => ({ ...p, lon: e.target.value }))}
              />
            </WideModalField>
          </WideModalSection>
        )}

        <WideModalSection columns={1}>
          <WideModalField label={t('stakeholders.ui.stakeholder.interests', { defaultValue: 'What they care about' })}>
            <textarea
              rows={2}
              className={FIELD_CLASS}
              value={draft.interests}
              onChange={(e) => set('interests', e.target.value)}
            />
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.stakeholder.expectations', { defaultValue: 'What they expect from the project' })}
          >
            <textarea
              rows={2}
              className={FIELD_CLASS}
              value={draft.expectations}
              onChange={(e) => set('expectations', e.target.value)}
            />
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.stakeholder.concerns', { defaultValue: 'What worries them' })}>
            <textarea
              rows={2}
              className={FIELD_CLASS}
              value={draft.concerns}
              onChange={(e) => set('concerns', e.target.value)}
            />
          </WideModalField>
          {stakeholder && (
            <WideModalField
              label={t('stakeholders.ui.stakeholder.status', { defaultValue: 'Status' })}
              htmlFor="stakeholder-status"
            >
              <select
                id="stakeholder-status"
                className={FIELD_CLASS}
                value={draft.status}
                onChange={(e) => set('status', e.target.value as typeof draft.status)}
              >
                {(Object.keys(STAKEHOLDER_STATUS) as Array<keyof typeof STAKEHOLDER_STATUS>).map((s) => (
                  <option key={s} value={s}>
                    {vocab(t, STAKEHOLDER_STATUS, s)}
                  </option>
                ))}
              </select>
            </WideModalField>
          )}
        </WideModalSection>
      </div>
    </WideModal>
  );
}
