// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import en from '../../app/locales/en';

// Course scripts quote these labels word for word; a rename updates the course in the same commit.
const STABLE: Record<string, string> = {
  'survey.page.register': 'Survey register',
  'survey.action.import_points': 'Import points',
  'survey.action.set_crs': 'Set project CRS',
  'survey.action.advanced': 'Advanced options',
  'survey.action.open_demo': 'Open demo project',
  'survey.duplicate.keep_first': 'Keep first',
  'survey.kind.control': 'Control',
  // Lesson 3 reads "78 rows read, 1 problem".
  'survey.import.rows_read_one': '{{rows}} rows read, {{count}} problem',
  'survey.import.rows_read_other': '{{rows}} rows read, {{count}} problems',
  'sidebar.group.survey': 'Survey & Land',
  'survey.action.new_traverse': 'New traverse',
  'survey.status.pass': 'Pass',
  'survey.status.fail': 'Fail',
  'volumes.page.title': 'Volumes',
  'volumes.action.new_surface': 'New surface',
  'volumes.action.new_volume': 'New volume',
  'volumes.action.confirm': 'Confirm result',
  'volumes.action.send_to_boq': 'Send to BOQ',
  'volumes.action.record_progress': 'Record progress',
  'volumes.action.print_report': 'Print report',
  'volumes.action.duplicate': 'Duplicate',
  'volumes.action.acknowledge': 'Acknowledge',
  'volumes.status.draft': 'Draft',
  'volumes.status.confirmed': 'Confirmed',
  'volumes.status.sent': 'Sent',
};

describe('survey stable names', () => {
  it('keep the English text the course quotes', () => {
    const translation = (en as { translation: Record<string, string> }).translation;
    for (const [key, text] of Object.entries(STABLE)) {
      expect(translation[key], key).toBe(text);
    }
  });
});
