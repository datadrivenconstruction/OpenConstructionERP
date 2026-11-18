// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui/ModuleGuide';

/** The mine survey lessons as spotlight cards, in the order the course runs them. */
export const mineGuide: ModuleGuideContent = {
  titleKey: 'mine.page.title',
  titleDefault: 'Mine survey',
  introKey: 'mine.guide.intro',
  introDefault: 'Compare the plan of each mining unit with the surveyed volume, check the truck count and add the confirmed volume to the claim.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'mine.action.new_period',
      titleDefault: 'New period',
      bodyKey: 'mine.guide.period_body',
      bodyDefault: 'Open the month, add a line per unit with its plan and set the compliance band.',
      spotlightSelector: '[data-testid="mine-new-period"]',
    },
    {
      icon: 'Layers',
      titleKey: 'mine.action.compute_actual',
      titleDefault: 'Compute actual',
      bodyKey: 'mine.guide.actual_body',
      bodyDefault: 'Pick the surface at the start and at the end of the month. The actual is the cut between them, never typed.',
      spotlightSelector: '[data-testid="mine-table"]',
    },
    {
      icon: 'Send',
      titleKey: 'mine.action.add_to_claim',
      titleDefault: 'Add to claim',
      bodyKey: 'mine.guide.claim_body',
      bodyDefault: 'Confirm the result, then add it to the progress claim against a BOQ line.',
      spotlightSelector: '[data-testid="mine-table"]',
    },
  ],
};
