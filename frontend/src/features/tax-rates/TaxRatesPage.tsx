// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tax Rates page.
 *
 * The explainer sits at page level, above the working area, so it stays
 * findable rather than disappearing with whatever is selected.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Percent } from 'lucide-react';

import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { PageHeader } from '@/shared/ui/PageHeader';

import { TaxRateResolverPanel } from './TaxRateResolverPanel';

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

export function TaxRatesPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <PageHeader srTitle={t('nav.tax_rates', { defaultValue: 'Tax Rates' })} />

      <CollapsibleSection
        storageKey="tax_rates.how"
        icon={<Percent size={15} className="text-oe-blue" />}
        title={t('tax_rates.flow_title', {
          defaultValue: 'How a tax rate is worked out, and when it declines to give one',
        })}
      >
        <p className="text-xs text-content-tertiary">
          {t('tax_rates.flow_intro', {
            defaultValue:
              'Some countries have one sales tax rate and some do not. Canada has a federal rate that one province replaces with a single harmonised one, that several add their own to, and that four charge on its own. There is no Canadian rate, only a rate for a place on a date, so this page asks for both before it answers.',
          })}
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
          <li>
            {t('tax_rates.flow_step1', {
              defaultValue:
                'Choose the country. Where the country charges by region, a region picker appears and starts empty rather than on a guess.',
            })}
          </li>
          <li>
            {t('tax_rates.flow_step2', {
              defaultValue:
                'Choose the region. Where a country charges by region there is no national figure to fall back on, so nothing is shown until this is answered.',
            })}
          </li>
          <li>
            {t('tax_rates.flow_step3', {
              defaultValue:
                'Read the combined rate and the layers under it. Each layer says what it is charged on, because a rate charged on a tax-inclusive amount adds more to the total than its own figure.',
            })}
          </li>
          <li>
            {t('tax_rates.flow_step4', {
              defaultValue:
                'Set a past date to read the rate that was in force then. Rates change, and a rate that changed mid-project is the reason a tender and an invoice can honestly disagree.',
            })}
          </li>
        </ol>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('tax_rates.flow_links', {
            defaultValue:
              'Where a rate cannot be given you get a question or a defect rather than a figure, and never a zero. A rate that looks right is the one mistake nobody catches downstream, so the page would rather be visibly unhelpful than quietly wrong.',
          })}
        </p>
        <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
          <span>
            <span className="font-medium text-content-secondary">
              {t('tax_rates.flow_connects', { defaultValue: 'Connects with:' })}
            </span>{' '}
            <ModLink to="/tax-withholding">
              {t('nav.tax_withholding', { defaultValue: 'Withholding Tax' })}
            </ModLink>
          </span>
        </div>
      </CollapsibleSection>

      <TaxRateResolverPanel />
    </div>
  );
}
