import type { CountryTemplate } from '../_shared/templateTypes';

/** Chinese GB/T 50500 template configuration. */
export const CN_TEMPLATE: CountryTemplate = {
  id: 'cn-gbt50500',
  name: 'GB/T 50500 \u5DE5\u7A0B\u91CF\u6E05\u5355',
  country: 'China',
  countryCode: 'CN',
  currency: 'CNY',
  currencySymbol: '\u00A5',
  classification: 'GB/T50500',
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

/** Chinese BOQ trade sections based on GB/T 50500 classification. */
export const CN_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: '\u571F\u77F3\u65B9\u5DE5\u7A0B (Earthworks)' },
  { code: '02', label: '\u6869\u57FA\u7840\u5DE5\u7A0B (Pile Foundations)' },
  { code: '03', label: '\u7838\u7B51\u5DE5\u7A0B (Masonry)' },
  { code: '04', label: '\u6DF7\u51DD\u571F\u53CA\u94A2\u7B4B\u6DF7\u51DD\u571F\u5DE5\u7A0B (Concrete & RC)' },
  { code: '05', label: '\u94A2\u7ED3\u6784\u5DE5\u7A0B (Steel Structures)' },
  { code: '06', label: '\u6728\u7ED3\u6784\u5DE5\u7A0B (Timber Structures)' },
  { code: '07', label: '\u5C4B\u9762\u53CA\u9632\u6C34\u5DE5\u7A0B (Roofing & Waterproofing)' },
  { code: '08', label: '\u4FDD\u6E29\u9694\u70ED\u9632\u8150\u5DE5\u7A0B (Insulation & Anti-corrosion)' },
  { code: '09', label: '\u697C\u5730\u9762\u88C5\u9970\u5DE5\u7A0B (Floor Finishes)' },
  { code: '10', label: '\u5899\u67F1\u9762\u88C5\u9970\u5DE5\u7A0B (Wall Finishes)' },
  { code: '11', label: '\u5929\u68DA\u5DE5\u7A0B (Ceiling Works)' },
  { code: '12', label: '\u95E8\u7A97\u5DE5\u7A0B (Doors & Windows)' },
  { code: '13', label: '\u6CB9\u6F06\u6D82\u6599\u88F1\u7CCA\u5DE5\u7A0B (Painting & Wallcovering)' },
  { code: '14', label: '\u63AA\u65BD\u9879\u76EE (Provisional Items)' },
  { code: '15', label: '\u5B89\u88C5\u5DE5\u7A0B (M&E Installation)' },
];

/** Validate a GB/T 50500 section code. Valid codes are two-digit numbers (01-15). */
export function isValidGBTCode(code: string): boolean {
  return /^(0[1-9]|1[0-5])$/.test(code.trim());
}
