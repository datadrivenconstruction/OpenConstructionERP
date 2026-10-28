// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The logistics plan of a project, as one tab of the site logistics page:
// a short lead, the parts of the plan as a second row of tabs, and the panel
// of the chosen part. The catalogue is read once here because every panel
// names its codes with it.

import { useState } from 'react';
import clsx from 'clsx';

import { CustomsPanel } from './CustomsPanel';
import { ConceptPanel, UtilitiesPanel } from './FlowPanels';
import { useCatalogue, useConcept, useWords } from './hooks';
import { NeighbourhoodPanel } from './NeighbourhoodPanel';
import { ReadinessPanel } from './ReadinessPanel';
import { AreasPanel, BalancePanel, StagesPanel } from './SitePanels';
import { SitePlanPanel } from './SitePlanPanel';
import { PermitsPanel, TransportsPanel } from './TransportPanels';
import { tx } from './texts';

export const PLAN_TABS = [
  'balance',
  'stages',
  'areas',
  'siteplan',
  'media',
  'concept',
  'transports',
  'permits',
  'customs',
  'neighbourhood',
  'readiness',
] as const;

export type PlanTab = (typeof PLAN_TABS)[number];

export function LogisticsPlan({ projectId, initialTab = 'balance' }: { projectId: string; initialTab?: PlanTab }) {
  const { t } = useWords();
  const [tab, setTab] = useState<PlanTab>(initialTab);
  // A failed catalogue does not block the plan: codes then read as plain words.
  const catalogue = useCatalogue(projectId).data ?? null;
  // Read with the plan, so that every dialog opened later knows the site clock.
  useConcept(projectId);
  const props = { projectId, catalogue };

  return (
    <div className="space-y-4" data-testid="logistics-plan">
      <p className="max-w-3xl text-sm text-content-secondary">{tx(t, 'intro')}</p>
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label={tx(t, 'sections')}>
        {PLAN_TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            data-testid={`plan-tab-${key}`}
            onClick={() => setTab(key)}
            className={clsx(
              'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
              tab === key
                ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                : 'border-border-light text-content-secondary hover:text-content-primary',
            )}
          >
            {tx(t, `tab.${key}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'balance' && <BalancePanel {...props} onGoTo={setTab} />}
        {tab === 'stages' && <StagesPanel {...props} />}
        {tab === 'areas' && <AreasPanel {...props} />}
        {tab === 'siteplan' && <SitePlanPanel {...props} />}
        {tab === 'media' && <UtilitiesPanel {...props} />}
        {tab === 'concept' && <ConceptPanel {...props} />}
        {tab === 'transports' && <TransportsPanel {...props} />}
        {tab === 'permits' && <PermitsPanel {...props} />}
        {tab === 'customs' && <CustomsPanel {...props} />}
        {tab === 'neighbourhood' && <NeighbourhoodPanel {...props} />}
        {tab === 'readiness' && <ReadinessPanel {...props} />}
      </div>
    </div>
  );
}
