// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cost Match page.
 *
 * The explainer sits at page level, above the working area, so switching
 * between the queue and the full record never takes it off the screen.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Layers } from 'lucide-react';

import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';

import { CostMatchPanel } from './CostMatchPanel';

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

export function CostMatchPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <CollapsibleSection
        storageKey="cost_match.how"
        icon={<Layers size={15} className="text-oe-blue" />}
        title={t('cost_match.flow_title', {
          defaultValue: 'How matching works, and what it will not do',
        })}
      >
        <p className="text-xs text-content-tertiary">
          {t('cost_match.flow_intro', {
            defaultValue:
              'Somebody sends you a bill written in their own words, and you need it priced in yours. This scores every line against a cost base you already trust, then hands you the ones it is not sure about. It never prices anything by itself.',
          })}
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
          <li>
            {t('cost_match.flow_step1', {
              defaultValue:
                'Paste the bill as it arrived and pin the base to match it against. The base is pinned to the run, so a line ruled on today cannot quietly refer to a catalogue that changed next month.',
            })}
          </li>
          <li>
            {t('cost_match.flow_step2', {
              defaultValue:
                'Every line comes back with a tier rather than a yes or no. Exact means the words and the unit both agreed. Nothing found means the base had nothing close, which is an answer and not a failure.',
            })}
          </li>
          <li>
            {t('cost_match.flow_step3', {
              defaultValue:
                'Work the queue. It holds only the lines the matcher is not claiming an answer for, so it is the shortest honest description of what is left to do.',
            })}
          </li>
          <li>
            {t('cost_match.flow_step4', {
              defaultValue:
                'Rule on each line: confirm what was suggested, price it against something you pick instead, or record that nothing in this base fits. Rulings are appended, never overwritten, so a change of mind stays visible.',
            })}
          </li>
        </ol>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('cost_match.flow_links', {
            defaultValue:
              'The base comes from Cost Data, and a confident line is still a proposal until somebody confirms it. Nothing here is applied automatically, which is why an empty queue is not the same as a finished run.',
          })}
        </p>
        <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
          <span>
            <span className="font-medium text-content-secondary">
              {t('cost_match.flow_connects', { defaultValue: 'Connects with:' })}
            </span>{' '}
            <ModLink to="/costs">{t('nav.costs', { defaultValue: 'Cost Database' })}</ModLink> ·{' '}
            <ModLink to="/cost-explorer">
              {t('nav.cost_explorer', { defaultValue: 'Cost Explorer' })}
            </ModLink>
          </span>
        </div>
      </CollapsibleSection>

      <CostMatchPanel />
    </div>
  );
}
