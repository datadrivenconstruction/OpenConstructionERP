// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Picking the procurement record a package or an owner-furnished item points
// to, by its number and title. The list comes from the module that owns the
// record. A kind without a list says so instead of showing an empty select,
// because "no list" and "no records" call for different next steps.

import { useTranslation } from 'react-i18next';

import { getErrorMessage } from '@/shared/lib/api';

import { Field, INPUT_CLASS } from './DeliveryBits';
import { useLinkTargets } from './hooks';
import type { LinkKind } from './linkTargets';

export interface RecordPickerProps {
  projectId: string;
  kind: LinkKind | null;
  value: string;
  onChange: (id: string) => void;
}

export function RecordPicker({ projectId, kind, value, onChange }: RecordPickerProps) {
  const { t } = useTranslation();
  const targetsQ = useLinkTargets(projectId, kind);
  if (!kind) return null;
  const label = t('delivery_model.ui.link.record', { defaultValue: 'Record' });

  if (targetsQ.isLoading) {
    return <p className="text-sm text-content-tertiary">{t('delivery_model.ui.loading', { defaultValue: 'Loading' })}</p>;
  }
  if (targetsQ.isError) {
    return (
      <p className="text-sm text-semantic-error" role="alert" data-testid="record-picker-error">
        {getErrorMessage(targetsQ.error)}
      </p>
    );
  }
  if (targetsQ.data === null) {
    return (
      <p className="text-sm text-content-secondary" data-testid="record-picker-unavailable">
        {t('delivery_model.ui.link.unavailable', {
          defaultValue: 'Records of this type cannot be listed here yet, so they cannot be linked from this screen.',
        })}
      </p>
    );
  }
  const targets = targetsQ.data ?? [];
  if (targets.length === 0) {
    return (
      <p className="text-sm text-content-secondary" data-testid="record-picker-empty">
        {t('delivery_model.ui.link.none', { defaultValue: 'This project has no record of this type yet. Create it first, then link it here.' })}
      </p>
    );
  }
  return (
    <Field label={label}>
      <select className={INPUT_CLASS} value={value} onChange={(e) => onChange(e.target.value)} data-testid="record-picker">
        <option value="">{t('delivery_model.ui.choose', { defaultValue: 'Choose' })}</option>
        {targets.map((target) => (
          <option key={target.id} value={target.id}>
            {target.code && target.title
              ? t('delivery_model.ui.link.code_and_title', { defaultValue: '{{code}} · {{title}}', code: target.code, title: target.title })
              : target.code || target.title}
          </option>
        ))}
      </select>
    </Field>
  );
}
