// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Full EVM page.
 *
 * The explainer sits at page level, above the tab strip, so it does not vanish
 * when the reader moves between progress, the plan and the forecast.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { LineChart } from 'lucide-react';

import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';

import { FullEvmPanel } from './FullEvmPanel';

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

export function FullEvmPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <CollapsibleSection
        storageKey="full_evm.how"
        icon={<LineChart size={15} className="text-oe-blue" />}
        title={t('full_evm.flow_title', {
          defaultValue: 'How earned value answers "are we actually on track"',
        })}
      >
        <p className="text-xs text-content-tertiary">
          {t('full_evm.flow_intro', {
            defaultValue:
              'Spending forty percent of a budget tells you nothing on its own. It is either half the story or all of it, depending on how much work that money bought. Earned value puts the three figures side by side: what was planned by now, what the completed work was worth, and what it cost.',
          })}
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
          <li>
            {t('full_evm.flow_step1', {
              defaultValue:
                'Set a baseline: the budget, and how it was expected to be spent period by period. Without the periods there is no curve, and planned value cannot be read at any date.',
            })}
          </li>
          <li>
            {t('full_evm.flow_step2', {
              defaultValue:
                'Check it and approve it. An approved baseline is what everything afterwards is measured against, so it is deliberately harder to change than a draft.',
            })}
          </li>
          <li>
            {t('full_evm.flow_step3', {
              defaultValue:
                'Record what has been earned and what has been spent, at a date. The indices follow from those two figures and the plan, and none of them is a judgement anybody entered by hand.',
            })}
          </li>
          <li>
            {t('full_evm.flow_step4', {
              defaultValue:
                'Read the forecast as a range rather than a number. Different formulas answer the outturn differently, and how far apart they sit is itself the useful signal.',
            })}
          </li>
        </ol>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('full_evm.flow_links', {
            defaultValue:
              'An index within half a percent of one is reported as on track, not ahead or behind, because a project called late at 0.998 teaches everybody to ignore the colour. Where the requested forecast formula could not run, the screen names the one that did.',
          })}
        </p>
        <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
          <span>
            <span className="font-medium text-content-secondary">
              {t('full_evm.flow_connects', { defaultValue: 'Connects with:' })}
            </span>{' '}
            <ModLink to="/finance">
              {t('nav.finance', { defaultValue: 'Finance' })}
            </ModLink> ·{' '}
            <ModLink to="/project-intelligence">
              {t('nav.project_intelligence', { defaultValue: 'Project Intelligence' })}
            </ModLink>
          </span>
        </div>
      </CollapsibleSection>

      <FullEvmPanel />
    </div>
  );
}
