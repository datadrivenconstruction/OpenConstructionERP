/**
 * Shared types for country-specific BOQ exchange modules.
 */

/** A BOQ position in the exchange format (normalized across all countries). */
export interface ExchangePosition {
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unitRate: number;
  total: number;
  section?: string;
  parentId?: string | null;
  isSection?: boolean;
  classification?: Record<string, string>; // e.g. { din276: '330', nrm: '2.6.1' }
}

/** Column mapping for Excel import — maps spreadsheet columns to ExchangePosition fields. */
export interface ColumnMapping {
  ordinal?: string;   // column letter or header name
  description?: string;
  unit?: string;
  quantity?: string;
  unitRate?: string;
  total?: string;
  section?: string;
  classification?: string;
}

/** Country-specific template config. */
export interface CountryTemplate {
  id: string;
  name: string;
  country: string;
  countryCode: string; // ISO 3166-1 alpha-2
  currency: string;
  currencySymbol: string;
  classification: string; // e.g. 'NRM', 'MasterFormat', 'Lots'
  defaultColumns: ColumnMapping;
  /** Which columns are mandatory for a valid import. */
  requiredColumns: (keyof ColumnMapping)[];
  /** File extensions accepted for import. */
  acceptedExtensions: string[];
}

/** Result of parsing an imported file. */
export interface ImportParseResult {
  positions: ExchangePosition[];
  warnings: string[];
  errors: string[];
  metadata?: {
    projectName?: string;
    boqName?: string;
    totalValue?: number;
    positionCount?: number;
  };
}

/** Result of an export operation. */
export interface ExportResult {
  blob: Blob;
  filename: string;
  positionCount: number;
  totalValue: number;
}
