import type { CountryTemplate } from '../_shared/templateTypes';

/** Spanish PBC / Base de Precios template configuration. */
export const ES_TEMPLATE: CountryTemplate = {
  id: 'es-pbc',
  name: 'PBC / Base de Precios',
  country: 'Spain',
  countryCode: 'ES',
  currency: 'EUR',
  currencySymbol: '\u20ac',
  classification: 'PBC',
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

/** Spanish BOQ chapters based on PBC / Base de Precios classification. */
export const ES_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: 'Actuaciones Previas (Preliminaries)' },
  { code: '02', label: 'Acondicionamiento del Terreno (Site Preparation)' },
  { code: '03', label: 'Cimentaciones (Foundations)' },
  { code: '04', label: 'Estructuras (Structures)' },
  { code: '05', label: 'Fachadas y Particiones (Facades & Partitions)' },
  { code: '06', label: 'Carpinter\u00eda y Cerrajer\u00eda (Joinery & Metalwork)' },
  { code: '07', label: 'Cubiertas (Roofing)' },
  { code: '08', label: 'Revestimientos y Acabados (Finishes)' },
  { code: '09', label: 'Instalaciones El\u00e9ctricas (Electrical)' },
  { code: '10', label: 'Fontaner\u00eda (Plumbing)' },
  { code: '11', label: 'Climatizaci\u00f3n (HVAC)' },
  { code: '12', label: 'Protecci\u00f3n contra Incendios (Fire Protection)' },
  { code: '13', label: 'Urbanizaci\u00f3n (External Works)' },
  { code: '14', label: 'Gesti\u00f3n de Residuos (Waste Management)' },
  { code: '15', label: 'Seguridad y Salud (Health & Safety)' },
];

/** Validate a PBC chapter code. Valid codes are two-digit strings optionally followed by a dot and sub-codes. */
export function isValidPBCCode(code: string): boolean {
  return /^\d{2}(\.\d{1,4})?$/.test(code.trim());
}
