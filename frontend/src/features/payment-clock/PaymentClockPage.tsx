// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Payment Clock page.
 *
 * The explainer sits at page level, above the working area, so it stays
 * findable rather than disappearing with whatever is selected.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Scale } from 'lucide-react';

import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';

import { PaymentClockPanel } from './PaymentClockPanel';

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

export function PaymentClockPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <CollapsibleSection
        storageKey="payment_clock.how"
        icon={<Scale size={15} className="text-oe-blue" />}
        title={t('payment_clock.flow_title', {
          defaultValue: 'How the payment clock works, and what it protects',
        })}
      >
        <p className="text-xs text-content-tertiary">
          {t('payment_clock.flow_intro', {
            defaultValue:
              'Construction payment statutes give each application a timetable, and missing a step on it changes what is legally payable. This module keeps that timetable per application so the deadline is known before it passes rather than after.',
          })}
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
          <li>
            {t('payment_clock.flow_step1', {
              defaultValue:
                'Open a clock over a payment application and pick the statutory regime the contract falls under.',
            })}
          </li>
          <li>
            {t('payment_clock.flow_step2', {
              defaultValue:
                'The due date, payment notice deadline, pay less deadline and final date for payment are computed from that regime, counting calendar or business days as the statute counts them.',
            })}
          </li>
          <li>
            {t('payment_clock.flow_step3', {
              defaultValue:
                'Record each notice as it is served. A notice served late is still recorded, because that fact is the point.',
            })}
          </li>
          <li>
            {t('payment_clock.flow_step4', {
              defaultValue:
                'The sum payable follows: where a valid notice was served it is the notified sum, and where the window closed it is the sum applied for.',
            })}
          </li>
        </ol>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('payment_clock.flow_links', {
            defaultValue:
              'Feeds from Contracts progress claims and Subcontractor payment applications, and its breaches show up in Validation.',
          })}
        </p>
        <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
          <span>
            <span className="font-medium text-content-secondary">
              {t('payment_clock.flow_pulls', { defaultValue: 'Pulls from:' })}
            </span>{' '}
            <ModLink to="/contracts">
              {t('nav.contracts', { defaultValue: 'Contracts' })}
            </ModLink> ·{' '}
            <ModLink to="/subcontractors">
              {t('nav.subcontractors', { defaultValue: 'Subcontractor Directory' })}
            </ModLink>
          </span>
          <span>
            <span className="font-medium text-content-secondary">
              {t('payment_clock.flow_feeds', { defaultValue: 'Feeds:' })}
            </span>{' '}
            <ModLink to="/validation">
              {t('nav.validation', { defaultValue: 'Validation' })}
            </ModLink>
          </span>
        </div>
      </CollapsibleSection>

      <PaymentClockPanel />
    </div>
  );
}
