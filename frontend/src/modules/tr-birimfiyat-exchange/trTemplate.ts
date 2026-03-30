import type { CountryTemplate } from '../_shared/templateTypes';

/** Turkish Bayindirlik Birim Fiyat template configuration. */
export const TR_TEMPLATE: CountryTemplate = {
  id: 'tr-birimfiyat',
  name: 'Bayindirlik Birim Fiyat',
  country: 'Turkey',
  countryCode: 'TR',
  currency: 'TRY',
  currencySymbol: '\u20BA',
  classification: 'BirimFiyat',
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

/** Turkish BOQ trade sections based on Bayindirlik Birim Fiyat classification. */
export const TR_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: 'Hafriyat Isleri (Excavation)' },
  { code: '04', label: 'Beton ve Betonarme Isleri (Concrete & RC)' },
  { code: '07', label: 'Ahsap Isleri (Timber Works)' },
  { code: '10', label: 'Demir Isleri (Ironwork)' },
  { code: '13', label: 'Cati Isleri (Roofing)' },
  { code: '15', label: 'Sihhi Tesisat (Plumbing)' },
  { code: '16', label: 'Kalorifer Tesisati (Heating)' },
  { code: '17', label: 'Havalandirma Tesisati (Ventilation)' },
  { code: '18', label: 'Elektrik Tesisati (Electrical)' },
  { code: '21', label: 'Boya Isleri (Painting)' },
  { code: '23', label: 'Kaplama Isleri (Cladding & Finishes)' },
  { code: '25', label: 'Insaat Demiri Isleri (Rebar)' },
  { code: '27', label: 'Yalitim Isleri (Insulation)' },
  { code: '30', label: 'Asansor (Elevators)' },
];

/** Validate a Birim Fiyat poz code. Valid codes are two digits optionally followed by a dot and more digits. */
export function isValidBirimFiyatCode(code: string): boolean {
  return /^\d{2}(\.\d{1,6})?$/.test(code.trim());
}
