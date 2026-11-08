// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pick the BIM model and element a device or pour belongs to. Renders nothing when the project has no model. */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { fetchBIMElements, fetchBIMModels } from '@/features/bim/api';
import { filterElements } from '../evidenceData';

const FIELD = 'h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary';
const LABEL = 'text-xs text-content-secondary';

export interface BimLink {
  modelId: string;
  elementId: string;
}

export function BimElementSelect({
  projectId,
  value,
  onChange,
}: {
  projectId: string;
  value: BimLink;
  onChange: (v: BimLink) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const modelsQ = useQuery({
    queryKey: ['site-sensors', 'bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: !!projectId,
  });
  const elementsQ = useQuery({
    queryKey: ['site-sensors', 'bim-elements', value.modelId],
    queryFn: () => fetchBIMElements(value.modelId, { skeleton: true, limit: 5000 }),
    enabled: !!value.modelId,
  });
  const models = (modelsQ.data?.items ?? []).filter((m) => m.status === 'ready');
  if (models.length === 0) return null;
  const { items, truncated } = filterElements(elementsQ.data?.items ?? [], query, 100);

  return (
    <>
      <label className={LABEL}>
        {t('site_sensors.bim.model', { defaultValue: 'BIM model' })}
        <select
          value={value.modelId}
          onChange={(e) => onChange({ modelId: e.target.value, elementId: '' })}
          className={`${FIELD} mt-1 w-full`}
        >
          <option value="">{t('site_sensors.bim.none', { defaultValue: 'Not linked' })}</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      {value.modelId && (
        <label className={LABEL}>
          {t('site_sensors.bim.element', { defaultValue: 'BIM element' })}
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('site_sensors.bim.search', { defaultValue: 'Search elements' })}
            aria-label={t('site_sensors.bim.search', { defaultValue: 'Search elements' })}
            className={`${FIELD} mt-1 w-full`}
          />
          <select
            value={value.elementId}
            onChange={(e) => onChange({ modelId: value.modelId, elementId: e.target.value })}
            className={`${FIELD} mt-1 w-full`}
          >
            <option value="">{t('site_sensors.bim.none', { defaultValue: 'Not linked' })}</option>
            {items.map((el) => (
              <option key={el.id} value={el.id}>
                {el.name || el.element_type}
                {el.storey ? ` (${el.storey})` : ''}
              </option>
            ))}
          </select>
          {truncated && (
            <span className="text-xs text-content-tertiary">
              {t('site_sensors.bim.truncated', {
                defaultValue: 'Showing the first {{count}} matches. Narrow the search.',
                count: items.length,
              })}
            </span>
          )}
        </label>
      )}
    </>
  );
}
