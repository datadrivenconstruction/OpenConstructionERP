// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** The four flagship demo projects (backend/app/core/demo_packs), same cards as the site. */
export interface FlagshipDemo {
  id: string;
  key: string;
  tag: string;
  title: string;
  forWho: string;
  points: [string, string, string];
}

export const FLAGSHIP_DEMOS: FlagshipDemo[] = [
  {
    id: 'consultancy-riyadh',
    key: 'consultancy',
    tag: 'Engineering consultancy',
    title: 'Al Narjis Villa Compound, Riyadh',
    forWho: 'Design and supervision firms, cost consultants',
    points: [
      'Fee plan by design stage and discipline',
      'Client cost estimate with Saudi Building Code references',
      'Supervision and fee invoicing by stage',
    ],
  },
  {
    id: 'contractor-jeddah',
    key: 'contractor',
    tag: 'Main contractor',
    title: 'Marina Heights Residential Tower, Jeddah',
    forWho: 'General contractors and estimators',
    points: [
      'Estimate, budget and procurement packages',
      'Execution and progress billing',
      '12-storey tower, about SAR 62 million',
    ],
  },
  {
    id: 'site-development-dammam',
    key: 'site',
    tag: 'Site development',
    title: 'Al Fanateer Community Park, Dammam',
    forWho: 'Infrastructure, landscaping and civil works teams',
    points: [
      'Earthworks, storm water and irrigation networks',
      'Roads, lighting, hard and soft landscape',
      '14-hectare park, about SAR 38 million',
    ],
  },
  {
    id: 'full-showcase-riyadh',
    key: 'full',
    tag: 'Full showcase',
    title: 'Al Malqa Business and Residence Hub, Riyadh',
    forWho: 'Anyone who wants to see the whole platform',
    points: [
      'Six business lines in one project',
      'From design fees to fit-out and FF&E',
      'Mixed-use hub, about SAR 78 million',
    ],
  },
];
