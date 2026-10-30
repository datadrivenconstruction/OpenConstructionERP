// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** The four flagship demo projects (backend/app/core/demo_packs), same cards as the site. */
export interface FlagshipDemo {
  id: string;
  /** i18n key stem for curated cards; null for a card built from catalog data. */
  key: string | null;
  tag: string;
  title: string;
  forWho: string;
  points: string[];
}

/** One row of `GET /api/demo/catalog`. */
export interface DemoCatalogRow {
  demo_id: string;
  name: string;
  description: string;
  country: string;
  budget?: string;
  type?: string;
}

/** Curated cards are all Saudi; the full showcase doubles as the market-neutral tour. */
const FLAGSHIP_COUNTRY = 'sa';
const NEUTRAL_DEMO_ID = 'full-showcase-riyadh';
const MAX_CARDS = 4;

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

/**
 * The demo cards for a market: the curated cards when they are that market's,
 * else the catalog's demos for that country, else the one neutral tour.
 *
 * @param country lower-case ISO 3166-1 alpha-2 of the chosen market.
 * @param catalog rows of the server's demo catalog.
 */
export function demosForMarket(
  country: string | null | undefined,
  catalog: DemoCatalogRow[],
): { demos: FlagshipDemo[]; matched: boolean } {
  const code = (country ?? '').toLowerCase();
  if (code === FLAGSHIP_COUNTRY) return { demos: FLAGSHIP_DEMOS, matched: true };
  const own = code
    ? catalog.filter((r) => r.country?.toLowerCase() === code).slice(0, MAX_CARDS)
    : [];
  if (own.length > 0) {
    return {
      matched: true,
      demos: own.map((r) => ({
        id: r.demo_id,
        key: null,
        tag: r.type ?? '',
        title: r.name,
        forWho: '',
        points: [r.description, r.budget ?? ''].filter(Boolean),
      })),
    };
  }
  return { demos: FLAGSHIP_DEMOS.filter((d) => d.id === NEUTRAL_DEMO_ID), matched: false };
}
