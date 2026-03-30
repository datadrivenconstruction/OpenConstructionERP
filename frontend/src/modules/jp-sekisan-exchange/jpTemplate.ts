import type { CountryTemplate } from '../_shared/templateTypes';

/** Japanese Sekisan Kijun template configuration. */
export const JP_TEMPLATE: CountryTemplate = {
  id: 'jp-sekisan',
  name: '\u7A4D\u7B97\u57FA\u6E96 (Sekisan Kijun)',
  country: 'Japan',
  countryCode: 'JP',
  currency: 'JPY',
  currencySymbol: '\u00A5',
  classification: 'Sekisan',
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

/** Japanese BOQ trade sections based on Sekisan Kijun classification. */
export const JP_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: '\u4EEE\u8A2D\u5DE5\u4E8B (Temporary Works)' },
  { code: '02', label: '\u571F\u5DE5\u4E8B (Earthworks)' },
  { code: '03', label: '\u5730\u696D\u5DE5\u4E8B (Ground Improvement)' },
  { code: '04', label: '\u9244\u7B4B\u5DE5\u4E8B (Reinforcement)' },
  { code: '05', label: '\u30B3\u30F3\u30AF\u30EA\u30FC\u30C8\u5DE5\u4E8B (Concrete)' },
  { code: '06', label: '\u9244\u9AA8\u5DE5\u4E8B (Steel Structure)' },
  { code: '07', label: '\u6728\u5DE5\u4E8B (Carpentry)' },
  { code: '08', label: '\u9632\u6C34\u5DE5\u4E8B (Waterproofing)' },
  { code: '09', label: '\u5DE6\u5B98\u5DE5\u4E8B (Plastering)' },
  { code: '10', label: '\u30BF\u30A4\u30EB\u5DE5\u4E8B (Tiling)' },
  { code: '11', label: '\u91D1\u5C5E\u5DE5\u4E8B (Metalwork)' },
  { code: '12', label: '\u5EFA\u5177\u5DE5\u4E8B (Doors & Windows)' },
  { code: '13', label: '\u5857\u88C5\u5DE5\u4E8B (Painting)' },
  { code: '14', label: '\u5185\u88C5\u5DE5\u4E8B (Interior Finishes)' },
  { code: '15', label: '\u6A5F\u68B0\u8A2D\u5099\u5DE5\u4E8B (Mechanical)' },
  { code: '16', label: '\u96FB\u6C17\u8A2D\u5099\u5DE5\u4E8B (Electrical)' },
];

/** Validate a Sekisan trade code. Valid codes are two digits optionally followed by a dot and more digits. */
export function isValidSekisanCode(code: string): boolean {
  return /^\d{2}(\.\d{1,6})?$/.test(code.trim());
}
