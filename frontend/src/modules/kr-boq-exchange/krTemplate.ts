import type { CountryTemplate } from '../_shared/templateTypes';

/** Korean \ud45c\uc900\ud488\uc148 (Standard Estimating) template configuration. */
export const KR_TEMPLATE: CountryTemplate = {
  id: 'kr-poomsem',
  name: '\ud45c\uc900\ud488\uc148 (Standard Estimating)',
  country: 'South Korea',
  countryCode: 'KR',
  currency: 'KRW',
  currencySymbol: '\u20a9',
  classification: 'Poomsem',
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

/** Korean BOQ trade sections based on \ud45c\uc900\ud488\uc148 classification. */
export const KR_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: '\uac00\uc124\uacf5\uc0ac (Temporary Works)' },
  { code: '02', label: '\ud1a0\uacf5\uc0ac (Earthworks)' },
  { code: '03', label: '\uae30\ucd08\uacf5\uc0ac (Foundation)' },
  { code: '04', label: '\ucca0\uadfc\ucf58\ud06c\ub9ac\ud2b8\uacf5\uc0ac (RC Works)' },
  { code: '05', label: '\ucca0\uace8\uacf5\uc0ac (Steel Structure)' },
  { code: '06', label: '\uc870\uc801\uacf5\uc0ac (Masonry)' },
  { code: '07', label: '\ubc29\uc218\uacf5\uc0ac (Waterproofing)' },
  { code: '08', label: '\ubbf8\uc7a5\uacf5\uc0ac (Plastering)' },
  { code: '09', label: '\ud0c0\uc77c\uacf5\uc0ac (Tiling)' },
  { code: '10', label: '\ubaa9\uacf5\uc0ac (Carpentry)' },
  { code: '11', label: '\ucc3d\ud638\uacf5\uc0ac (Windows & Doors)' },
  { code: '12', label: '\ub3c4\uc7a5\uacf5\uc0ac (Painting)' },
  { code: '13', label: '\uae08\uc18d\uacf5\uc0ac (Metalwork)' },
  { code: '14', label: '\uae30\uacc4\uc124\ube44\uacf5\uc0ac (Mechanical)' },
  { code: '15', label: '\uc804\uae30\uc124\ube44\uacf5\uc0ac (Electrical)' },
  { code: '16', label: '\uc870\uacbd\uacf5\uc0ac (Landscaping)' },
];

/** Validate a Poomsem section code. Valid codes are two digits optionally followed by a dot and sub-digits. */
export function isValidPoomsemCode(code: string): boolean {
  return /^\d{2}(\.\d{1,4})?$/.test(code.trim());
}
