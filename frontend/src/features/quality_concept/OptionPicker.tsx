// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One picker for every field that names a record of another module: a
// contact, a schedule activity, a handover act, a document. The server lists
// what this reader may choose; the field stores the id.
//
// A list the server cannot offer is not an empty list. It says so with a
// reason, and the field then takes the reference as typed.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { OptionKind } from './api';
import { useOptions } from './hooks';
import { humanizeCode } from './labels';
import { Hint, inputCls } from './QualityBits';

export function OptionPicker({
  projectId,
  kind,
  value,
  onChange,
  currentLabel,
  testId,
}: {
  projectId: string;
  kind: OptionKind;
  value: string;
  onChange: (id: string) => void;
  /** The name of the stored choice, shown while the list does not hold it. */
  currentLabel?: string | null;
  testId?: string;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const options = useOptions(projectId, kind, q);

  if (options.data && !options.data.available) {
    const reason = options.data.reason;
    return (
      <div className="space-y-1">
        <input className={inputCls} value={value} onChange={(e) => onChange(e.target.value.trim())} data-testid={testId} />
        <Hint>
          {reason
            ? t(`quality_concept.errors.${reason}`, { defaultValue: humanizeCode(reason) })
            : t('qualityConcept.options.unavailable', { defaultValue: 'No list can be offered here. Enter the reference.' })}
        </Hint>
      </div>
    );
  }

  const items = options.data?.items ?? [];
  const listed = items.some((i) => i.id === value);
  return (
    <div className="space-y-1">
      <input
        type="search"
        className={inputCls}
        value={q}
        placeholder={t('qualityConcept.options.search', { defaultValue: 'Search' })}
        aria-label={t('qualityConcept.options.search', { defaultValue: 'Search' })}
        onChange={(e) => setQ(e.target.value)}
      />
      <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId}>
        <option value="">{t('qualityConcept.common.none', { defaultValue: 'None' })}</option>
        {/* The stored choice stays selected while the search shows other rows. */}
        {value && !listed && (
          <option value={value}>
            {currentLabel || t('qualityConcept.options.current', { defaultValue: 'Current selection' })}
          </option>
        )}
        {items.map((i) => (
          <option key={i.id} value={i.id}>
            {i.label}
          </option>
        ))}
      </select>
    </div>
  );
}
