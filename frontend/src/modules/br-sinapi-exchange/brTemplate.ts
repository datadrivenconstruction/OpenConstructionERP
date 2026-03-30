import type { CountryTemplate } from '../_shared/templateTypes';

/** Brazilian SINAPI/TCPO template configuration. */
export const BR_TEMPLATE: CountryTemplate = {
  id: 'br-sinapi',
  name: 'SINAPI / TCPO',
  country: 'Brazil',
  countryCode: 'BR',
  currency: 'BRL',
  currencySymbol: 'R$',
  classification: 'SINAPI',
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

/** Brazilian BOQ trade sections based on SINAPI classification. */
export const BR_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: 'Servi\u00e7os Preliminares (Preliminaries)' },
  { code: '02', label: 'Movimento de Terra (Earthworks)' },
  { code: '03', label: 'Funda\u00e7\u00f5es (Foundations)' },
  { code: '04', label: 'Estrutura (Structure)' },
  { code: '05', label: 'Alvenaria (Masonry)' },
  { code: '06', label: 'Cobertura (Roofing)' },
  { code: '07', label: 'Impermeabiliza\u00e7\u00e3o (Waterproofing)' },
  { code: '08', label: 'Revestimento (Rendering & Finishes)' },
  { code: '09', label: 'Pavimenta\u00e7\u00e3o (Flooring)' },
  { code: '10', label: 'Esquadrias (Doors & Windows)' },
  { code: '11', label: 'Pintura (Painting)' },
  { code: '12', label: 'Instala\u00e7\u00f5es Hidr\u00e1ulicas (Plumbing)' },
  { code: '13', label: 'Instala\u00e7\u00f5es El\u00e9tricas (Electrical)' },
  { code: '14', label: 'Instala\u00e7\u00f5es Especiais (Special Installations)' },
  { code: '15', label: 'Complementos (Complements)' },
];

/** Validate a SINAPI section code. Valid codes are two-digit strings. */
export function isValidSINAPICode(code: string): boolean {
  return /^\d{2}(\.\d{1,5})?$/.test(code.trim());
}
