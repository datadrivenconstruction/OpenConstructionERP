import type { CountryTemplate } from '../_shared/templateTypes';

/** Italian Computo Metrico / Prezzario DEI template configuration. */
export const IT_TEMPLATE: CountryTemplate = {
  id: 'it-computo',
  name: 'Computo Metrico / Prezzario DEI',
  country: 'Italy',
  countryCode: 'IT',
  currency: 'EUR',
  currencySymbol: '\u20AC',
  classification: 'ComputoMetrico',
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

/** Italian BOQ trade sections based on Computo Metrico classification. */
export const IT_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: 'Demolizioni e Scavi (Demolition & Excavation)' },
  { code: '02', label: 'Fondazioni (Foundations)' },
  { code: '03', label: 'Strutture in C.A. (RC Structures)' },
  { code: '04', label: 'Strutture in Acciaio (Steel Structures)' },
  { code: '05', label: 'Murature (Masonry)' },
  { code: '06', label: 'Solai e Coperture (Floors & Roofing)' },
  { code: '07', label: 'Impermeabilizzazioni (Waterproofing)' },
  { code: '08', label: 'Intonaci e Rivestimenti (Plaster & Cladding)' },
  { code: '09', label: 'Pavimentazioni (Flooring)' },
  { code: '10', label: 'Serramenti (Doors & Windows)' },
  { code: '11', label: 'Opere in Ferro (Metalwork)' },
  { code: '12', label: 'Tinteggiature (Painting)' },
  { code: '13', label: 'Impianto Idrico-Sanitario (Plumbing)' },
  { code: '14', label: 'Impianto Termico (Heating)' },
  { code: '15', label: 'Impianto Elettrico (Electrical)' },
  { code: '16', label: 'Opere Esterne (External Works)' },
  { code: '17', label: 'Sicurezza (Safety)' },
];

/** Validate a Computo Metrico capitolo code. Valid codes are two digits optionally followed by a dot and more digits. */
export function isValidComputoCode(code: string): boolean {
  return /^\d{2}(\.\d{1,6})?$/.test(code.trim());
}
