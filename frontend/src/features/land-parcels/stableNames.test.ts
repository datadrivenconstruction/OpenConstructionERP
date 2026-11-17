// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import en from '../../app/locales/en';

// Course scripts and UX.md quote these labels word for word; a rename updates the course in the same commit.
const STABLE: Record<string, string> = {
  'survey.parcels.title': 'Land & parcels',
  'survey.parcels.btn.import': 'Import parcels',
  'survey.parcels.btn.export': 'Export',
  'survey.parcels.btn.print': 'Print schedule',
  'survey.parcels.btn.send_to_boq': 'Send to BOQ',
  'survey.parcels.status.needed': 'Needed',
  'survey.parcels.status.negotiating': 'Negotiating',
  'survey.parcels.status.acquired': 'Acquired',
  'survey.parcels.status.expropriation': 'Expropriation',
  'survey.parcels.col.parcel_id': 'Parcel ID',
};

describe('land parcels stable names', () => {
  it('keep the English text the course quotes', () => {
    const translation = (en as { translation: Record<string, string> }).translation;
    for (const [key, text] of Object.entries(STABLE)) {
      expect(translation[key], key).toBe(text);
    }
  });
});
