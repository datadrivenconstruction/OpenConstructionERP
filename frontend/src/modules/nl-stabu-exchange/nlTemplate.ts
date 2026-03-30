import type { CountryTemplate } from '../_shared/templateTypes';

/** Dutch STABU / RAW template configuration. */
export const NL_TEMPLATE: CountryTemplate = {
  id: 'nl-stabu',
  name: 'STABU / RAW',
  country: 'Netherlands',
  countryCode: 'NL',
  currency: 'EUR',
  currencySymbol: '\u20ac',
  classification: 'STABU',
  defaultColumns: {
    ordinal: '0',
    description: '1',
    unit: '2',
    quantity: '3',
    unitRate: '4',
    total: '5',
    classification: '6',
  },
  requiredColumns: ['description', 'quantity'],
  acceptedExtensions: ['.csv', '.tsv', '.xlsx'],
};

/** Dutch BOQ trade sections based on STABU classification. */
export const NL_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '00', label: 'Algemeen (General)' },
  { code: '01', label: 'Grondwerk (Earthworks)' },
  { code: '03', label: 'Beton- en Metselwerk (Concrete & Masonry)' },
  { code: '04', label: 'Staalconstructies (Steel Structures)' },
  { code: '05', label: 'Houtconstructies (Timber Structures)' },
  { code: '06', label: 'Metaalwerken (Metalwork)' },
  { code: '20', label: 'Daken (Roofing)' },
  { code: '21', label: 'Beglazing (Glazing)' },
  { code: '22', label: 'Kozijnen en Deuren (Frames & Doors)' },
  { code: '30', label: 'Stukadoorwerk (Plastering)' },
  { code: '31', label: 'Tegelwerk (Tiling)' },
  { code: '33', label: 'Plafonds (Ceilings)' },
  { code: '34', label: 'Schilderwerk (Painting)' },
  { code: '40', label: 'Sanitair (Sanitary)' },
  { code: '41', label: 'Verwarming (Heating)' },
  { code: '42', label: 'Ventilatie (Ventilation)' },
  { code: '43', label: 'Elektra (Electrical)' },
  { code: '50', label: 'Terreinwerk (External Works)' },
];

/** Validate a STABU chapter code. Valid codes are two digits. */
export function isValidSTABUCode(code: string): boolean {
  return /^\d{2}(\.\d{1,4})?$/.test(code.trim());
}
