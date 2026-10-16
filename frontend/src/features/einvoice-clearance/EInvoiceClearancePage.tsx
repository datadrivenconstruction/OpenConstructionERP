// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * E-invoice Clearance page.
 *
 * The explainer sits at page level, above the working area, so it stays
 * findable rather than disappearing with whatever is selected.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Landmark } from 'lucide-react';

import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';

import { EInvoiceClearancePanel } from './EInvoiceClearancePanel';

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

export function EInvoiceClearancePage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <CollapsibleSection
        storageKey="einvoice_clearance.how"
        icon={<Landmark size={15} className="text-oe-blue" />}
        title={t('einvoice_clearance.flow_title', {
          defaultValue: 'How clearance works, and what it records',
        })}
      >
        <p className="text-xs text-content-tertiary">
          {t('einvoice_clearance.flow_intro', {
            defaultValue:
              'In much of the world an invoice is not a private document between two parties. A tax authority sees it, and in many countries it is not legally valid until that authority has answered. This module records what the authority actually answered, in its own words, for every invoice sent to one.',
          })}
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
          <li>
            {t('einvoice_clearance.flow_step1', {
              defaultValue:
                'Register the legal entity that issues the invoices with the country platform it issues them through. The registration is the only record of the identity a submission was sent under.',
            })}
          </li>
          <li>
            {t('einvoice_clearance.flow_step2', {
              defaultValue:
                'An invoice is prepared for that platform, in that country format, with the national fields the format needs and the EN 16931 semantic model has nowhere to put.',
            })}
          </li>
          <li>
            {t('einvoice_clearance.flow_step3', {
              defaultValue:
                'Check it against the country rules first. That is a dry run and sends nothing, so a missing national field turns up at your desk rather than three minutes before the month closes.',
            })}
          </li>
          <li>
            {t('einvoice_clearance.flow_step4', {
              defaultValue:
                'Send it, and whatever comes back is stored as it came. An acceptance means three different things depending on the country: cleared by an authority, reported to one, or simply delivered to the buyer over a network with no authority in it.',
            })}
          </li>
        </ol>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('einvoice_clearance.flow_links', {
            defaultValue:
              'Documents are built by the EN 16931 engine where a country uses a format it covers, and clear against the invoices in Finance. A rejection is kept with the authority code beside it, because that code is what anybody investigating will ask for.',
          })}
        </p>
        <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
          <span>
            <span className="font-medium text-content-secondary">
              {t('einvoice_clearance.flow_connects', { defaultValue: 'Connects with:' })}
            </span>{' '}
            <ModLink to="/finance">
              {t('nav.finance', { defaultValue: 'Finance' })}
            </ModLink>
          </span>
        </div>
      </CollapsibleSection>

      <EInvoiceClearancePanel />
    </div>
  );
}
