import type { CountryTemplate } from '../_shared/templateTypes';

/** Polish KNR / KNNR template configuration. */
export const PL_TEMPLATE: CountryTemplate = {
  id: 'pl-knr',
  name: 'KNR / KNNR',
  country: 'Poland',
  countryCode: 'PL',
  currency: 'PLN',
  currencySymbol: 'z\u0142',
  classification: 'KNR',
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

/** Polish BOQ trade sections based on KNR classification. */
export const PL_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: 'Roboty ziemne (Earthworks)' },
  { code: '02', label: 'Fundamenty (Foundations)' },
  { code: '03', label: 'Konstrukcje \u017celbetowe (RC Structures)' },
  { code: '04', label: 'Konstrukcje stalowe (Steel Structures)' },
  { code: '05', label: 'Roboty murowe (Masonry)' },
  { code: '06', label: 'Konstrukcje drewniane (Timber)' },
  { code: '07', label: 'Pokrycia dachowe (Roofing)' },
  { code: '08', label: 'Izolacje (Insulation)' },
  { code: '09', label: 'Tynki i ok\u0142adziny (Plaster & Cladding)' },
  { code: '10', label: 'Posadzki (Flooring)' },
  { code: '11', label: 'Stolarka (Joinery)' },
  { code: '12', label: '\u015alusarka (Metalwork)' },
  { code: '13', label: 'Malowanie (Painting)' },
  { code: '14', label: 'Instalacje sanitarne (Sanitary)' },
  { code: '15', label: 'Instalacje elektryczne (Electrical)' },
  { code: '16', label: 'Instalacje grzewcze (Heating)' },
  { code: '17', label: 'Wentylacja (Ventilation)' },
  { code: '18', label: 'Roboty zewn\u0119trzne (External Works)' },
];

/** Validate a KNR section code. Valid codes are two digits optionally followed by a dash and more digits. */
export function isValidKNRCode(code: string): boolean {
  return /^\d{2}(-\d{1,4})?$/.test(code.trim());
}
