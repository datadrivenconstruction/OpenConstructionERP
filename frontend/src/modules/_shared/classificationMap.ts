/**
 * Classification cross-reference mapping.
 * Maps between DIN 276, NRM 1/2, MasterFormat, and other country standards.
 */

export interface ClassificationMapping {
  din276?: string;
  din276Label?: string;
  nrm?: string;
  nrmLabel?: string;
  masterformat?: string;
  masterformatLabel?: string;
  lots?: string; // French lots techniques
  lotsLabel?: string;
  acmm?: string; // Australian
  acmmLabel?: string;
  description: string;
}

/** Core cross-reference table — major construction categories. */
export const CLASSIFICATION_MAP: ClassificationMapping[] = [
  // Substructure
  { din276: '310', nrm: '1.1', masterformat: '31 00 00', lots: 'Lot 1', acmm: 'A', description: 'Substructure / Earthworks' },
  { din276: '320', nrm: '1.1.4', masterformat: '31 60 00', lots: 'Lot 1', acmm: 'A', description: 'Foundations' },
  { din276: '321', nrm: '1.1.6', masterformat: '31 63 00', lots: 'Lot 1', acmm: 'A', description: 'Shallow foundations' },
  { din276: '322', nrm: '1.1.7', masterformat: '31 66 00', lots: 'Lot 1', acmm: 'A', description: 'Deep foundations' },
  // Superstructure — Concrete
  { din276: '330', nrm: '2.1', masterformat: '03 30 00', lots: 'Lot 2', acmm: 'B', description: 'External walls' },
  { din276: '331', nrm: '2.1.1', masterformat: '03 31 00', lots: 'Lot 2', acmm: 'B', description: 'Load-bearing external walls' },
  { din276: '332', nrm: '2.1.2', masterformat: '04 20 00', lots: 'Lot 2', acmm: 'B', description: 'Non-load-bearing external walls' },
  { din276: '340', nrm: '2.2', masterformat: '03 30 00', lots: 'Lot 2', acmm: 'B', description: 'Internal walls' },
  { din276: '350', nrm: '2.3', masterformat: '03 30 00', lots: 'Lot 3', acmm: 'C', description: 'Floors / slabs' },
  { din276: '360', nrm: '2.4', masterformat: '03 30 00', lots: 'Lot 3', acmm: 'C', description: 'Roofs' },
  // Finishes
  { din276: '370', nrm: '3.1', masterformat: '09 00 00', lots: 'Lot 6', acmm: 'D', description: 'Wall finishes' },
  { din276: '371', nrm: '3.2', masterformat: '09 60 00', lots: 'Lot 6', acmm: 'D', description: 'Floor finishes' },
  { din276: '372', nrm: '3.3', masterformat: '09 50 00', lots: 'Lot 6', acmm: 'D', description: 'Ceiling finishes' },
  // MEP
  { din276: '410', nrm: '5.1', masterformat: '22 00 00', lots: 'Lot 8', acmm: 'E', description: 'Sanitary installations' },
  { din276: '420', nrm: '5.3', masterformat: '23 00 00', lots: 'Lot 9', acmm: 'E', description: 'Heating installations' },
  { din276: '430', nrm: '5.4', masterformat: '23 70 00', lots: 'Lot 10', acmm: 'E', description: 'Ventilation / AC' },
  { din276: '440', nrm: '5.6', masterformat: '26 00 00', lots: 'Lot 7', acmm: 'F', description: 'Electrical installations' },
  { din276: '450', nrm: '5.8', masterformat: '27 00 00', lots: 'Lot 7', acmm: 'F', description: 'Telecom / data installations' },
  // External works
  { din276: '510', nrm: '8.1', masterformat: '32 10 00', lots: 'Lot 12', acmm: 'G', description: 'External surfaces / roads' },
  { din276: '520', nrm: '8.2', masterformat: '32 90 00', lots: 'Lot 11', acmm: 'G', description: 'Landscaping' },
  { din276: '530', nrm: '8.3', masterformat: '33 00 00', lots: 'Lot 12', acmm: 'G', description: 'External services' },
];

/** Look up a classification by one standard and get the cross-reference. */
export function lookupClassification(
  standard: 'din276' | 'nrm' | 'masterformat' | 'lots' | 'acmm',
  code: string,
): ClassificationMapping | undefined {
  return CLASSIFICATION_MAP.find((m) => m[standard] === code);
}

/** Map a code from one standard to another. */
export function mapClassification(
  fromStandard: 'din276' | 'nrm' | 'masterformat' | 'lots' | 'acmm',
  toStandard: 'din276' | 'nrm' | 'masterformat' | 'lots' | 'acmm',
  code: string,
): string | undefined {
  const mapping = lookupClassification(fromStandard, code);
  return mapping?.[toStandard] ?? undefined;
}
