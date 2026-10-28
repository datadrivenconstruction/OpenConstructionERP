// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// riskGuide - "How it works" content for the Risk Register module.
// Consumed by <ModuleGuideButton content={riskGuide} /> on RiskRegisterPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const riskGuide: ModuleGuideContent = {
  titleKey: 'guide.risk.title',
  titleDefault: 'Risk Register',
  introKey: 'guide.risk.intro',
  introDefault:
    'The risk register is where you log what could go wrong on a project and score how much it matters. Capture each threat once with its probability and impact, then read your exposure on a matrix and pressure-test it with a Monte Carlo simulation.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.risk.register.title',
      titleDefault: 'Log a risk',
      bodyKey: 'guide.risk.register.body',
      bodyDefault:
        'Click Add Risk to record a threat with a title, category, probability, cost and schedule impact, severity and an owner. Each saved risk gets a code and a computed risk score, and the four cards at the top track your total risks, high and critical count, total exposure and how many are mitigated.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.risk.scoring.title',
      titleDefault: 'Probability times impact',
      bodyKey: 'guide.risk.scoring.body',
      bodyDefault:
        'Every risk is scored by multiplying its probability against its impact, so the items most likely to hurt the project rise to the top. Probability is a percentage and severity runs from low to critical, which together drive the score, the colour coding and where the risk lands on the matrix.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.risk.matrix.title',
      titleDefault: 'Read the matrix and heatmap',
      bodyKey: 'guide.risk.matrix.body',
      bodyDefault:
        'The probability-by-impact matrix and the 5 by 5 heatmap show how many risks sit in each cell, shaded green through red as severity climbs. Use them to see at a glance where the project is most exposed and which risks demand attention first.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.risk.triage.title',
      titleDefault: 'Triage and mitigate',
      bodyKey: 'guide.risk.triage.body',
      bodyDefault:
        'Search by code or title and filter by category or status to focus on a slice of the register. Open any row to set its status, write a mitigation strategy and a contingency plan, and review similar risks and their mitigations from across your projects.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.risk.montecarlo.title',
      titleDefault: 'Monte Carlo simulation',
      bodyKey: 'guide.risk.montecarlo.body',
      bodyDefault:
        'The Monte Carlo tab runs thousands of iterations over the whole register to model cost and schedule outcomes. It returns P50, P80 and P95 confidence bands, a distribution histogram and a tornado chart that ranks which risks drive the most uncertainty.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.risk.crosslinks.title',
      titleDefault: 'Carry risk into planning',
      bodyKey: 'guide.risk.crosslinks.body',
      bodyDefault:
        'A risk with schedule slip or cost exposure links straight to the 4D Schedule and the 5D cost model so you can buffer the timeline and set contingency. The planning cross-links keep the project context as you move between risk, schedule and cost work.',
    },
  ],
  ctaKey: 'guide.risk.cta',
  ctaDefault: 'Add your first risk',
};
