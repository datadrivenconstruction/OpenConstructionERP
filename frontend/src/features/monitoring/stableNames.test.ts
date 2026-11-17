// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import en from '../../app/locales/en';

// Course scripts quote these labels word for word; a rename updates the course in the same commit.
const STABLE: Record<string, string> = {
  'survey.page.monitoring': 'Monitoring',
  'survey.monitoring.action.import_readings': 'Import readings',
  'survey.monitoring.action.print_report': 'Print alarm report',
  'survey.monitoring.action.acknowledge': 'Acknowledge',
  'survey.monitoring.level.ok': 'OK',
  'survey.monitoring.level.alert': 'Alert',
  'survey.monitoring.level.action': 'Action',
  'survey.monitoring.level.alarm': 'Alarm',
};

describe('monitoring stable names', () => {
  it('keep the English text the course quotes', () => {
    const translation = (en as { translation: Record<string, string> }).translation;
    for (const [key, text] of Object.entries(STABLE)) {
      expect(translation[key], key).toBe(text);
    }
  });
});
