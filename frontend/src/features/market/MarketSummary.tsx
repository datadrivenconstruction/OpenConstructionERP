// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Onboarding line: what the derived market profile sets up, changeable later. */
import { useTranslation } from 'react-i18next';
import { useMarketScope } from './api';

export function MarketSummary() {
  const { t } = useTranslation();
  const { data } = useMarketScope();
  if (!data) return null;
  const s = data.standards ?? {};
  const parts = [s.classification, s.measurement, s.contract_family, data.units_system, s.tax_profile]
    .filter((v): v is string => !!v && v !== 'both')
    .map((v) => v.toUpperCase().replace(/_/g, ' '));
  if (parts.length === 0) return null;
  return (
    <p className="rounded-lg bg-surface-secondary px-3 py-2 text-xs text-content-secondary" data-testid="market-onboarding-summary">
      {t('market.onboarding_sets', { defaultValue: 'This sets up: {{items}}', items: parts.join(' · ') })}{' '}
      <span className="text-content-tertiary">{t('market.change_later', { defaultValue: 'You can change this later in Settings > Market & standards.' })}</span>
    </p>
  );
}
