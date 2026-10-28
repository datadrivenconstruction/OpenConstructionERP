// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Adding a plant item, or editing one. What the item is comes first (code,
// title, kind of plant, quantity); the requirements a supplier must meet and
// the two judgement calls (critical, long-lead) follow. An edit sends only the
// fields that changed, because an item past enquiry refuses any touch of its
// specification.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { WideModal, WideModalSection } from '@/shared/ui/WideModal';

import { createItem, updateItem, type PlantCatalogue, type PlantItem, type VendorBoundReason } from './api';
import { ITEM_CLASS, VENDOR_POLICY, VENDOR_REASON, catalogueName, errorText, vocab, type LabelContext } from './labels';
import { DialogFooter, Field, Refusal, fieldClass, usePlantCan, withheldReason } from './PlantBits';
import {
  classificationFrozen,
  emptyItemDraft,
  itemChanges,
  itemDraftOf,
  itemProblems,
  toCreateInput,
  type ItemDraft,
  type Override,
} from './rules';

const VENDOR_REASONS: VendorBoundReason[] = ['standardisation', 'existing_estate', 'warranty', 'sole_source'];
const OVERRIDES: Override[] = ['default', 'yes', 'no'];

export interface ItemDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** The item to edit, or null to add one. */
  item: PlantItem | null;
  catalogue: PlantCatalogue;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onSaved: (item: PlantItem) => void;
}

export function ItemDialog({ open, onClose, projectId, item, catalogue, labels, personName, onSaved }: ItemDialogProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ItemDraft>(() => (item ? itemDraftOf(item) : emptyItemDraft()));
  const [tried, setTried] = useState(false);
  const creating = !item;
  const problems = itemProblems(draft, creating);
  const set = <K extends keyof ItemDraft>(key: K, value: ItemDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const save = useMutation({
    mutationFn: () =>
      item ? updateItem(projectId, item.id, itemChanges(item, draft)) : createItem(projectId, toCreateInput(draft)),
    onSuccess: onSaved,
  });
  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };

  // The two overrides need the manage capability and stop changing once the route is set.
  const manage = usePlantCan().manage;
  const overrideLock =
    withheldReason(t, manage, 'manage_required') ??
    (item && classificationFrozen(item.status) ? errorText(t, 'classification_frozen') : null);
  const overrideLabel = (value: Override, kind: 'critical' | 'long_lead') => {
    if (value === 'default') {
      return kind === 'critical'
        ? t('plant.item.override.class_default', { defaultValue: 'As the kind of plant says' })
        : t('plant.item.override.lead_default', { defaultValue: 'As the lead time says' });
    }
    return value === 'yes'
      ? t('plant.common.yes', { defaultValue: 'Yes' })
      : t('plant.common.no', { defaultValue: 'No' });
  };
  const setRow = (index: number, patch: Partial<ItemDraft['performance'][number]>) =>
    set(
      'performance',
      draft.performance.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    );

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="xl"
      testId="plant-item-dialog"
      title={
        item
          ? t('plant.item.edit_title', { defaultValue: 'Edit {{code}}', code: item.code })
          : t('plant.item.add_title', { defaultValue: 'Add a plant item' })
      }
      subtitle={t('plant.item.dialog_subtitle', {
        defaultValue:
          'One line per piece of plant or equipment the project has to get on time. Lead times, dates and the route are added on the item afterwards.',
      })}
      footer={
        <DialogFooter
          problems={problems}
          showProblems={tried}
          busy={save.isPending}
          submitLabel={
            creating
              ? t('plant.item.add_submit', { defaultValue: 'Add item' })
              : t('plant.common.save', { defaultValue: 'Save' })
          }
          onCancel={onClose}
          onSubmit={submit}
        />
      }
    >
      <div className="space-y-5">
        <Refusal error={save.error} />

        <WideModalSection title={t('plant.item.section_what', { defaultValue: 'What it is' })} columns={3}>
          <Field label={t('plant.field.code', { defaultValue: 'Code' })} required={creating}>
            {(id) => (
              <input
                id={id}
                className={fieldClass}
                value={draft.code}
                disabled={!creating}
                placeholder="PL-001"
                onChange={(e) => set('code', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.field.title', { defaultValue: 'Title' })} required className="sm:col-span-2">
            {(id) => <input id={id} className={fieldClass} value={draft.title} onChange={(e) => set('title', e.target.value)} />}
          </Field>
          <Field
            label={t('plant.item.kind', { defaultValue: 'Kind of plant' })}
            required
            hint={t('plant.item.kind_hint', {
              defaultValue: 'Sets the typical lead time, how old a quote may be and whether the item is critical.',
            })}
          >
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.component_class_code}
                onChange={(e) => set('component_class_code', e.target.value)}
              >
                <option value="">{t('plant.common.choose', { defaultValue: 'Choose' })}</option>
                {(['main_component', 'user_equipment', 'operating_equipment'] as const).map((group) => (
                  <optgroup key={group} label={vocab(t, ITEM_CLASS, group)}>
                    {catalogue.component_classes
                      .filter((c) => c.item_class === group)
                      .map((c) => (
                        <option key={c.code} value={c.code}>
                          {catalogueName(labels, catalogue, 'component_classes', c.code)}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('plant.field.quantity', { defaultValue: 'Quantity' })} required>
            {(id) => (
              <input
                id={id}
                inputMode="decimal"
                className={fieldClass}
                value={draft.quantity}
                onChange={(e) => set('quantity', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.item.unit', { defaultValue: 'Unit' })}>
            {(id) => <input id={id} className={fieldClass} value={draft.unit} onChange={(e) => set('unit', e.target.value)} />}
          </Field>
          <Field
            label={t('plant.item.tag', { defaultValue: 'Tag' })}
            hint={t('plant.item.tag_hint', { defaultValue: 'The equipment number on the drawings, if it has one.' })}
          >
            {(id) => <input id={id} className={fieldClass} value={draft.tag} onChange={(e) => set('tag', e.target.value)} />}
          </Field>
          <Field label={t('plant.item.space', { defaultValue: 'Location' })}>
            {(id) => (
              <input id={id} className={fieldClass} value={draft.space_ref} onChange={(e) => set('space_ref', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.item.owner', { defaultValue: 'Responsible person' })}>
            {(id) => (
              <ProjectPeopleSelect
                id={id}
                projectId={projectId}
                value={draft.owner_user_id}
                displayValue={personName(draft.owner_user_id) ?? undefined}
                onChange={(userId) => set('owner_user_id', userId)}
              />
            )}
          </Field>
          <Field label={t('plant.item.description', { defaultValue: 'Description' })} className="sm:col-span-2 lg:col-span-3">
            {(id) => (
              <textarea
                id={id}
                rows={2}
                className={fieldClass}
                value={draft.description}
                onChange={(e) => set('description', e.target.value)}
              />
            )}
          </Field>
        </WideModalSection>

        <WideModalSection
          title={t('plant.item.section_spec', { defaultValue: 'What it must do' })}
          description={t('plant.item.section_spec_hint', {
            defaultValue: 'The requirements a supplier is asked to meet. They are frozen once the item is enquired.',
          })}
          columns={3}
        >
          <Field label={t('plant.field.redundancy', { defaultValue: 'Redundancy' })}>
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.redundancy_scheme}
                onChange={(e) => set('redundancy_scheme', e.target.value)}
              >
                <option value="">{t('plant.common.not_set', { defaultValue: 'Not set' })}</option>
                {catalogue.redundancy_schemes.map((s) => (
                  <option key={s.code} value={s.code}>
                    {catalogueName(labels, catalogue, 'redundancy_schemes', s.code)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('plant.field.vendor_policy', { defaultValue: 'Vendor policy' })}>
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.vendor_policy}
                onChange={(e) => set('vendor_policy', e.target.value as ItemDraft['vendor_policy'])}
              >
                {(['neutral', 'bound'] as const).map((v) => (
                  <option key={v} value={v}>
                    {vocab(t, VENDOR_POLICY, v)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          {draft.vendor_policy === 'bound' && (
            <Field label={t('plant.field.vendor_bound_reason', { defaultValue: 'Reason for vendor binding' })} required>
              {(id) => (
                <select
                  id={id}
                  className={fieldClass}
                  value={draft.vendor_bound_reason}
                  onChange={(e) => set('vendor_bound_reason', e.target.value)}
                >
                  <option value="">{t('plant.common.choose', { defaultValue: 'Choose' })}</option>
                  {VENDOR_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {vocab(t, VENDOR_REASON, r)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          )}
          <Field label={t('plant.item.maintenance', { defaultValue: 'Maintenance' })}>
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.maintenance_strategy}
                onChange={(e) => set('maintenance_strategy', e.target.value)}
              >
                <option value="">{t('plant.common.not_set', { defaultValue: 'Not set' })}</option>
                {catalogue.maintenance_strategies.map((s) => (
                  <option key={s.code} value={s.code}>
                    {catalogueName(labels, catalogue, 'maintenance_strategies', s.code)}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </WideModalSection>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('plant.field.performance', { defaultValue: 'Performance requirements' })}
            </h3>
            <Button
              size="sm"
              variant="secondary"
              icon={<Plus size={14} />}
              onClick={() => set('performance', [...draft.performance, { key: '', value: '', unit: '' }])}
            >
              {t('plant.item.add_requirement', { defaultValue: 'Add requirement' })}
            </Button>
          </div>
          {draft.performance.length === 0 && (
            <p className="text-xs text-content-tertiary">
              {t('plant.item.no_requirements', {
                defaultValue: 'No requirements yet. Add the figures a supplier has to meet, for example rated power 2500 kVA.',
              })}
            </p>
          )}
          {draft.performance.map((row, index) => (
            <div key={index} className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto]" data-testid="performance-row">
              <input
                aria-label={t('plant.item.requirement_name', { defaultValue: 'Requirement' })}
                placeholder={t('plant.item.requirement_name', { defaultValue: 'Requirement' })}
                className={fieldClass}
                value={row.key}
                onChange={(e) => setRow(index, { key: e.target.value })}
              />
              <input
                aria-label={t('plant.item.requirement_value', { defaultValue: 'Value' })}
                placeholder={t('plant.item.requirement_value', { defaultValue: 'Value' })}
                className={fieldClass}
                value={row.value}
                onChange={(e) => setRow(index, { value: e.target.value })}
              />
              <input
                aria-label={t('plant.item.unit', { defaultValue: 'Unit' })}
                placeholder={t('plant.item.unit', { defaultValue: 'Unit' })}
                className={fieldClass}
                value={row.unit}
                onChange={(e) => setRow(index, { unit: e.target.value })}
              />
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 size={14} />}
                aria-label={t('plant.item.remove_requirement', { defaultValue: 'Remove requirement {{n}}', n: index + 1 })}
                onClick={() =>
                  set(
                    'performance',
                    draft.performance.filter((_, i) => i !== index),
                  )
                }
              />
            </div>
          ))}
        </div>

        <WideModalSection
          title={t('plant.item.section_dates', { defaultValue: 'When it is needed and how it is treated' })}
          columns={3}
        >
          <Field
            label={t('plant.field.need_date', { defaultValue: 'Need date' })}
            hint={t('plant.item.need_date_hint', {
              defaultValue: 'The day it has to be on site. The latest order date is counted back from it.',
            })}
          >
            {(id) => (
              <input
                id={id}
                type="date"
                className={fieldClass}
                value={draft.need_date_fixed}
                onChange={(e) => set('need_date_fixed', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.field.critical', { defaultValue: 'Critical' })} hint={overrideLock ?? undefined}>
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.critical}
                disabled={overrideLock !== null}
                data-testid="item-critical-override"
                onChange={(e) => set('critical', e.target.value as Override)}
              >
                {OVERRIDES.map((o) => (
                  <option key={o} value={o}>
                    {overrideLabel(o, 'critical')}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('plant.item.long_lead', { defaultValue: 'Long-lead' })} hint={overrideLock ?? undefined}>
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.long_lead}
                disabled={overrideLock !== null}
                data-testid="item-long-lead-override"
                onChange={(e) => set('long_lead', e.target.value as Override)}
              >
                {OVERRIDES.map((o) => (
                  <option key={o} value={o}>
                    {overrideLabel(o, 'long_lead')}
                  </option>
                ))}
              </select>
            )}
          </Field>
          {draft.critical !== 'default' && (
            <Field
              label={t('plant.item.critical_reason', { defaultValue: 'Why the criticality differs' })}
              required
              className="sm:col-span-2 lg:col-span-3"
            >
              {(id) => (
                <textarea
                  id={id}
                  rows={2}
                  className={fieldClass}
                  value={draft.critical_reason}
                  disabled={overrideLock !== null}
                  onChange={(e) => set('critical_reason', e.target.value)}
                />
              )}
            </Field>
          )}
          {draft.long_lead !== 'default' && (
            <Field
              label={t('plant.item.long_lead_reason', { defaultValue: 'Why the long-lead classification differs' })}
              required
              className="sm:col-span-2 lg:col-span-3"
            >
              {(id) => (
                <textarea
                  id={id}
                  rows={2}
                  className={fieldClass}
                  value={draft.long_lead_override_reason}
                  disabled={overrideLock !== null}
                  onChange={(e) => set('long_lead_override_reason', e.target.value)}
                />
              )}
            </Field>
          )}
        </WideModalSection>
      </div>
    </WideModal>
  );
}
