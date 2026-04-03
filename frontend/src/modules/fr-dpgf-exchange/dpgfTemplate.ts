import type { CountryTemplate } from '../_shared/templateTypes';

/** France DPGF/DQE template configuration. */
export const DPGF_TEMPLATE: CountryTemplate = {
  id: 'fr-dpgf',
  name: 'France DPGF/DQE',
  country: 'France',
  countryCode: 'FR',
  currency: 'EUR',
  currencySymbol: '\u20ac',
  classification: 'Lots',
  defaultColumns: {
    ordinal: '0',
    description: '1',
    unit: '2',
    quantity: '3',
    unitRate: '4',
    total: '5',
    section: '6',
  },
  requiredColumns: ['description', 'quantity'],
  acceptedExtensions: ['.csv', '.tsv', '.xlsx'],
};

/** French Lots techniques (trade-based work packages). */
export const LOTS_TECHNIQUES: { code: string; label: string; labelFr: string }[] = [
  { code: '1', label: 'Earthworks & Foundations', labelFr: 'Terrassement & Fondations' },
  { code: '2', label: 'Structural works (concrete)', labelFr: 'Gros oeuvre (beton)' },
  { code: '3', label: 'Structural steelwork', labelFr: 'Charpente metallique' },
  { code: '4', label: 'Timber frame / Carpentry', labelFr: 'Charpente bois / Menuiserie' },
  { code: '5', label: 'Roofing & Waterproofing', labelFr: 'Couverture & Etancheite' },
  { code: '6', label: 'Facades & Cladding', labelFr: 'Facades & Bardage' },
  { code: '7', label: 'Electrical installations', labelFr: 'Electricite' },
  { code: '8', label: 'Plumbing & Sanitary', labelFr: 'Plomberie & Sanitaire' },
  { code: '9', label: 'HVAC', labelFr: 'CVC (Chauffage Ventilation Climatisation)' },
  { code: '10', label: 'Fire protection', labelFr: 'Protection incendie' },
  { code: '11', label: 'Landscaping', labelFr: 'Amenagements exterieurs' },
  { code: '12', label: 'Painting & Wallcovering', labelFr: 'Peinture & Revetements muraux' },
  { code: '13', label: 'Floor finishes', labelFr: 'Revetements de sol' },
  { code: '14', label: 'Joinery & Ironmongery', labelFr: 'Menuiserie & Serrurerie' },
  { code: '15', label: 'Lifts & Escalators', labelFr: 'Ascenseurs & Escaliers mecaniques' },
];

/** Validate a Lot technique code (1-15). */
export function isValidLotCode(code: string): boolean {
  const num = parseInt(code, 10);
  return !isNaN(num) && num >= 1 && num <= 99;
}
