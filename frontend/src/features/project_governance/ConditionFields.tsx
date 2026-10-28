// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The fields of one condition: what must be done, for which area and frame
// document, who owns it, by when and how severe. The decision dialog and the
// "add a condition" form on a decided gate share it, so a condition reads the
// same wherever it is written.
//
// The document belongs to the area: the server lifts a missing required
// document only for the matching pair (area, document type), so the document
// list follows the chosen area and is cleared when the area changes.

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';

import type { ConditionInput, GateArea, Severity } from './api';
import { areaDocumentTypes } from './decisionRules';
import { SEVERITY, vocab } from './labels';

const SEVERITIES: Severity[] = ['critical', 'essential', 'recommended'];

const fieldClass =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-60';

export interface ConditionFieldsProps {
  projectId: string;
  value: ConditionInput;
  areas: GateArea[];
  areaName: (code: string) => string;
  documentName: (docType: string) => string;
  onChange: (patch: Partial<ConditionInput>) => void;
  /** Sits beside the text field, for example the button that removes the row. */
  trailing?: ReactNode;
}

export function ConditionFields({
  projectId,
  value,
  areas,
  areaName,
  documentName,
  onChange,
  trailing,
}: ConditionFieldsProps) {
  const { t } = useTranslation();
  const docTypes = areaDocumentTypes(areas, value.area_code);

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <input
          aria-label={t('governance.project.decision.condition_text', { defaultValue: 'What must be done' })}
          placeholder={t('governance.project.decision.condition_text', { defaultValue: 'What must be done' })}
          className={fieldClass}
          value={value.text}
          onChange={(e) => onChange({ text: e.target.value })}
        />
        {trailing}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <select
          aria-label={t('governance.project.decision.condition_area', { defaultValue: 'Area' })}
          className={fieldClass}
          value={value.area_code ?? ''}
          onChange={(e) => onChange({ area_code: e.target.value, document_type: '' })}
        >
          <option value="">{t('governance.project.decision.whole_gate', { defaultValue: 'Whole gate' })}</option>
          {areas.map((a) => (
            <option key={a.area_id} value={a.code}>
              {areaName(a.code)}
            </option>
          ))}
        </select>
        <select
          aria-label={t('governance.project.decision.condition_document', { defaultValue: 'Frame document' })}
          className={fieldClass}
          value={value.document_type ?? ''}
          disabled={docTypes.length === 0}
          onChange={(e) => onChange({ document_type: e.target.value })}
        >
          <option value="">
            {t('governance.project.decision.no_document', { defaultValue: 'No specific document' })}
          </option>
          {docTypes.map((code) => (
            <option key={code} value={code}>
              {documentName(code)}
            </option>
          ))}
        </select>
        <ProjectPeopleSelect
          projectId={projectId}
          value={value.owner_user_id ?? ''}
          onChange={(userId) => onChange({ owner_user_id: userId })}
          placeholder={t('governance.project.decision.condition_owner', { defaultValue: 'Owner' })}
        />
        <input
          type="date"
          aria-label={t('governance.project.decision.condition_due', { defaultValue: 'Due date' })}
          className={fieldClass}
          value={value.due_date ?? ''}
          onChange={(e) => onChange({ due_date: e.target.value })}
        />
        <select
          aria-label={t('governance.project.decision.condition_severity', { defaultValue: 'Severity' })}
          className={fieldClass}
          value={value.severity}
          onChange={(e) => onChange({ severity: e.target.value as Severity })}
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {vocab(t, SEVERITY, s)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
