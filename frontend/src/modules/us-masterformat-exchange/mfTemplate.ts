import type { CountryTemplate } from '../_shared/templateTypes';

export const MF_TEMPLATE: CountryTemplate = {
  id: 'us-masterformat',
  name: 'US MasterFormat',
  country: 'United States',
  countryCode: 'US',
  currency: 'USD',
  currencySymbol: '$',
  classification: 'MasterFormat',
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

/** CSI MasterFormat divisions. */
export const MF_DIVISIONS: { code: string; label: string }[] = [
  { code: '00', label: 'Procurement and Contracting Requirements' },
  { code: '01', label: 'General Requirements' },
  { code: '02', label: 'Existing Conditions' },
  { code: '03', label: 'Concrete' },
  { code: '04', label: 'Masonry' },
  { code: '05', label: 'Metals' },
  { code: '06', label: 'Wood, Plastics, and Composites' },
  { code: '07', label: 'Thermal and Moisture Protection' },
  { code: '08', label: 'Openings' },
  { code: '09', label: 'Finishes' },
  { code: '10', label: 'Specialties' },
  { code: '11', label: 'Equipment' },
  { code: '12', label: 'Furnishings' },
  { code: '13', label: 'Special Construction' },
  { code: '14', label: 'Conveying Equipment' },
  { code: '21', label: 'Fire Suppression' },
  { code: '22', label: 'Plumbing' },
  { code: '23', label: 'Heating, Ventilating, and Air Conditioning (HVAC)' },
  { code: '25', label: 'Integrated Automation' },
  { code: '26', label: 'Electrical' },
  { code: '27', label: 'Communications' },
  { code: '28', label: 'Electronic Safety and Security' },
  { code: '31', label: 'Earthwork' },
  { code: '32', label: 'Exterior Improvements' },
  { code: '33', label: 'Utilities' },
  { code: '34', label: 'Transportation' },
  { code: '35', label: 'Waterway and Marine Construction' },
  { code: '40', label: 'Process Integration' },
  { code: '41', label: 'Material Processing and Handling Equipment' },
  { code: '42', label: 'Process Heating, Cooling, and Drying Equipment' },
  { code: '43', label: 'Process Gas and Liquid Handling' },
  { code: '44', label: 'Pollution and Waste Control Equipment' },
  { code: '45', label: 'Industry-Specific Manufacturing Equipment' },
  { code: '46', label: 'Water and Wastewater Equipment' },
  { code: '48', label: 'Electrical Power Generation' },
];

/** Validate a MasterFormat code (xx xx xx format). */
export function isValidMasterFormatCode(code: string): boolean {
  const clean = code.replace(/\s+/g, ' ').trim();
  return /^\d{2}(\s\d{2}){0,2}$/.test(clean);
}
