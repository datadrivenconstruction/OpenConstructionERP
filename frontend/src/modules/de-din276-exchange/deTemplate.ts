import type { CountryTemplate } from '../_shared/templateTypes';

/** DIN 276 template configuration for Germany/Austria/Switzerland. */
export const DE_TEMPLATE: CountryTemplate = {
  id: 'de-din276',
  name: 'DIN 276 / ÖNORM / SIA',
  country: 'Germany/Austria/Switzerland',
  countryCode: 'DE',
  currency: 'EUR',
  currencySymbol: '\u20AC',
  classification: 'DIN276',
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

/** DIN 276 Kostengruppen (cost groups) for DACH construction classification. */
export const DE_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '100', label: 'Grundstück' },
  { code: '200', label: 'Vorbereitende Maßnahmen' },
  { code: '300', label: 'Bauwerk \u2014 Baukonstruktionen' },
  { code: '310', label: 'Baugrube/Erdbau' },
  { code: '320', label: 'Gründung' },
  { code: '330', label: 'Außenwände' },
  { code: '340', label: 'Innenwände' },
  { code: '350', label: 'Decken' },
  { code: '360', label: 'Dächer' },
  { code: '370', label: 'Baukonstruktive Einbauten' },
  { code: '390', label: 'Sonstige Baukonstruktionen' },
  { code: '400', label: 'Bauwerk \u2014 Technische Anlagen' },
  { code: '410', label: 'Abwasser-, Wasser-, Gasanlagen' },
  { code: '420', label: 'Wärmeversorgungsanlagen' },
  { code: '430', label: 'Lufttechnische Anlagen' },
  { code: '440', label: 'Starkstromanlagen' },
  { code: '450', label: 'Fernmelde- und IT-Anlagen' },
  { code: '460', label: 'Förderanlagen' },
  { code: '470', label: 'Nutzungsspezifische Anlagen' },
  { code: '480', label: 'Gebäudeautomation' },
  { code: '500', label: 'Außenanlagen und Freiflächen' },
  { code: '600', label: 'Ausstattung und Kunstwerke' },
  { code: '700', label: 'Baunebenkosten' },
];

/** Validate a DIN 276 Kostengruppe code. Valid codes are 3-digit numbers (100-799). */
export function isValidDIN276Code(code: string): boolean {
  return /^[1-7]\d{2}$/.test(code.trim());
}
