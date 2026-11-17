// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import en from '../../app/locales/en';

// Course scripts quote these labels word for word; a rename updates the course in the same commit.
const STABLE: Record<string, string> = {
  'survey.page.setting_out': 'Setting-out',
  'survey.setting_out.action.new_request': 'New request',
  'survey.setting_out.action.print_sheet': 'Print sheet',
  'survey.setting_out.action.create_ncr': 'Create NCR draft',
  'survey.setting_out.status.pass': 'Pass',
  'survey.setting_out.status.fail': 'Fail',
  'survey.setting_out.status.no_tolerance': 'No profile, set one',
  'survey.setting_out.kpi.ncr_drafts': 'NCR drafts',
  'survey.setting_out.profile.demo': 'Demo values, not a standard',
};

describe('setting-out stable names', () => {
  it('keep the English text the course quotes', () => {
    const translation = (en as { translation: Record<string, string> }).translation;
    for (const [key, text] of Object.entries(STABLE)) {
      expect(translation[key], key).toBe(text);
    }
  });
});
