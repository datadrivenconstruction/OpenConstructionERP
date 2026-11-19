// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "How it works" content for central purchasing; translations live in the locale files.

import type { ModuleGuideContent } from '@/shared/ui';

export const centralPurchasingGuide: ModuleGuideContent = {
  titleKey: 'guide.central_purchasing.title',
  titleDefault: 'Central purchasing',
  introKey: 'guide.central_purchasing.intro',
  introDefault:
    'Tender one trade or material for several projects at once, get the volume price, and still give every project its own contract, its own budget check and its own cost report.',
  sections: [
    {
      icon: 'Building2',
      titleKey: 'guide.central_purchasing.projects.title',
      titleDefault: 'Projects and budgets',
      bodyKey: 'guide.central_purchasing.projects.body',
      bodyDefault:
        'Add the projects that buy this trade. Each one brings the company that runs it and its budget, taken from the planned amounts on its cost lines or typed in.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.central_purchasing.shares.title',
      titleDefault: 'Lines and shares',
      bodyKey: 'guide.central_purchasing.shares.body',
      bodyDefault:
        'Type each line once with the bundle quantity, then each project\'s share. The shares must add up to the line, and a share is booked on the project\'s cost line with the same cost code.',
    },
    {
      icon: 'Calculator',
      titleKey: 'guide.central_purchasing.split.title',
      titleDefault: 'The award split',
      bodyKey: 'guide.central_purchasing.split.body',
      bodyDefault:
        'Enter the awarded rates and a discount or an agreed lump sum. The split shows what each project pays, to the cent, and warns when a project goes over its budget.',
    },
    {
      icon: 'FileSignature',
      titleKey: 'guide.central_purchasing.award.title',
      titleDefault: 'Award and call-offs',
      bodyKey: 'guide.central_purchasing.award.body',
      bodyDefault:
        'Award drafts one contract or purchase order per project, or one framework agreement per company with call-offs from its projects. Nothing is signed until a person approves each draft. Project teams see only their own share.',
    },
  ],
};
