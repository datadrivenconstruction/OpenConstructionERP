import type { CountryTemplate } from '../_shared/templateTypes';

/** Czech URS / TSKP BOQ template configuration. */
export const CZ_TEMPLATE: CountryTemplate = {
  id: 'cz-urs',
  name: 'URS / TSKP',
  country: 'Czech Republic',
  countryCode: 'CZ',
  currency: 'CZK',
  currencySymbol: 'Kc',
  classification: 'URS',
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

/** Czech BOQ trade sections based on TSKP classification. */
export const CZ_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '1', label: 'Zemni prace (Earthworks)' },
  { code: '2', label: 'Zakladani (Foundations)' },
  { code: '3', label: 'Svisle konstrukce (Vertical Structures)' },
  { code: '4', label: 'Vodorovne konstrukce (Horizontal Structures)' },
  { code: '5', label: 'Komunikace (Roads & Pavements)' },
  { code: '6', label: 'Upravy povrchu (Surface Finishes)' },
  { code: '61', label: 'Omitky (Plaster)' },
  { code: '62', label: 'Obklady (Cladding)' },
  { code: '63', label: 'Podlahy (Flooring)' },
  { code: '7', label: 'Izolace (Insulation)' },
  { code: '8', label: 'Potrubi (Piping)' },
  { code: '9', label: 'Ostatni konstrukce (Other Structures)' },
  { code: '91', label: 'Doplnky (Accessories)' },
  { code: '94', label: 'Leseni (Scaffolding)' },
  { code: '95', label: 'Dokoncovaci prace (Finishing)' },
  { code: '96', label: 'Bourani (Demolition)' },
  { code: '97', label: 'Prorazeni otvoru (Openings)' },
  { code: '99', label: 'Presun hmot (Material Transport)' },
];

/** Validate a Czech URS / TSKP code. */
export function isValidCZCode(code: string): boolean {
  const clean = code.trim();
  // Accepts codes like "1", "3", "61", "94", "99", or longer URS codes like "311.23-1234"
  return /^\d{1,3}(\.\d{1,4}){0,3}(-\d{1,4})?$/.test(clean);
}
