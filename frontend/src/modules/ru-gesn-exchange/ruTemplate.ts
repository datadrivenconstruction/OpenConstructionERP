import type { CountryTemplate } from '../_shared/templateTypes';

/** Russian GESN / FER / TER template configuration. */
export const RU_TEMPLATE: CountryTemplate = {
  id: 'ru-gesn',
  name: '\u0413\u042d\u0421\u041d / \u0424\u0415\u0420 / \u0422\u0415\u0420',
  country: 'Russia',
  countryCode: 'RU',
  currency: 'RUB',
  currencySymbol: '\u20bd',
  classification: 'GESN',
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

/** Russian BOQ sections based on GESN collection structure. */
export const RU_TRADE_SECTIONS: { code: string; label: string }[] = [
  { code: '01', label: '\u0417\u0435\u043c\u043b\u044f\u043d\u044b\u0435 \u0440\u0430\u0431\u043e\u0442\u044b (Earthworks)' },
  { code: '06', label: '\u0411\u0435\u0442\u043e\u043d\u043d\u044b\u0435 \u0438 \u0436\u0435\u043b\u0435\u0437\u043e\u0431\u0435\u0442\u043e\u043d\u043d\u044b\u0435 \u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0438 (Concrete & RC)' },
  { code: '07', label: '\u0411\u0435\u0442\u043e\u043d\u043d\u044b\u0435 \u0438 \u0436\u0435\u043b\u0435\u0437\u043e\u0431\u0435\u0442\u043e\u043d\u043d\u044b\u0435 \u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0438 \u0441\u0431\u043e\u0440\u043d\u044b\u0435 (Precast Concrete)' },
  { code: '08', label: '\u041a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0438 \u0438\u0437 \u043a\u0438\u0440\u043f\u0438\u0447\u0430 \u0438 \u0431\u043b\u043e\u043a\u043e\u0432 (Masonry)' },
  { code: '09', label: '\u0421\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u043c\u0435\u0442\u0430\u043b\u043b\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0438 (Steel Structures)' },
  { code: '10', label: '\u0414\u0435\u0440\u0435\u0432\u044f\u043d\u043d\u044b\u0435 \u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0438 (Timber Structures)' },
  { code: '11', label: '\u041f\u043e\u043b\u044b (Flooring)' },
  { code: '12', label: '\u041a\u0440\u043e\u0432\u043b\u0438 (Roofing)' },
  { code: '13', label: '\u0417\u0430\u0449\u0438\u0442\u0430 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0439 (Protective Coatings)' },
  { code: '15', label: '\u041e\u0442\u0434\u0435\u043b\u043e\u0447\u043d\u044b\u0435 \u0440\u0430\u0431\u043e\u0442\u044b (Finishing Works)' },
  { code: '16', label: '\u0421\u0430\u043d\u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b (Plumbing)' },
  { code: '17', label: '\u042d\u043b\u0435\u043a\u0442\u0440\u043e\u043c\u043e\u043d\u0442\u0430\u0436\u043d\u044b\u0435 \u0440\u0430\u0431\u043e\u0442\u044b (Electrical)' },
  { code: '18', label: '\u041e\u0442\u043e\u043f\u043b\u0435\u043d\u0438\u0435 (Heating)' },
  { code: '19', label: '\u0412\u0435\u043d\u0442\u0438\u043b\u044f\u0446\u0438\u044f \u0438 \u043a\u043e\u043d\u0434\u0438\u0446\u0438\u043e\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435 (HVAC)' },
  { code: '20', label: '\u0412\u0440\u0435\u043c\u0435\u043d\u043d\u044b\u0435 \u0437\u0434\u0430\u043d\u0438\u044f \u0438 \u0441\u043e\u043e\u0440\u0443\u0436\u0435\u043d\u0438\u044f (Temporary Works)' },
  { code: '46', label: '\u0420\u0430\u0431\u043e\u0442\u044b \u043f\u043e \u0440\u0435\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438\u0438 (Reconstruction)' },
];

/** Validate a GESN collection code. Valid codes are two-digit strings optionally followed by sub-codes. */
export function isValidGESNCode(code: string): boolean {
  return /^\d{2}(-\d{2}(-\d{3}(-\d{1,2})?)?)?$/.test(code.trim());
}
