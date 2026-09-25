// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the product says a company profile does. Four strings promised that
// applying a profile rebuilds the sidebar. It does not: a profile switches
// modules on and off, only a handful of menu rows carry a module gate, and
// only a profile with its own workspace (`PRESET_WORKSPACES`) reshapes the
// Simple-mode menu. The strings were replaced under new keys, so no language
// keeps the old promise through a stale translation, and these checks keep
// the retired keys from coming back.
//
// Run:  npx vitest run src/features/modules/__tests__/profileMenuClaims.test.ts
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { PRESET_WORKSPACES } from '@/app/layout/workspaces';

const LOCALES = join(__dirname, '..', '..', '..', 'app', 'locales');

const RETIRED = [
  'modules.intro_body',
  'modules.intro_more',
  'onboarding.modules_subtitle_menu',
  'whatsnew.v1110.onboarding.b2',
];

const REPLACEMENTS = [
  'modules.intro_body_profiles',
  'modules.intro_more_profiles',
  'onboarding.modules_subtitle_switch',
  'whatsnew.v1110.onboarding.b2_modules',
];

const files = readdirSync(LOCALES).filter((f) => f.endsWith('.ts'));

describe('what a company profile is said to do', () => {
  it.each(files)('%s carries none of the keys that promised a rebuilt sidebar', (file) => {
    const text = readFileSync(join(LOCALES, file), 'utf-8');
    for (const key of RETIRED) {
      expect(text.includes(`"${key}":`), `${file}: ${key}`).toBe(false);
    }
  });

  it('every full locale says what a profile does in its own language', () => {
    // en-GB resolves through en; every other file that carried the old keys
    // carries the replacements.
    for (const file of files.filter((f) => f !== 'en-GB.ts' && f !== 'en-US.ts')) {
      const text = readFileSync(join(LOCALES, file), 'utf-8');
      for (const key of REPLACEMENTS) {
        expect(text.includes(`"${key}":`), `${file}: ${key}`).toBe(true);
      }
    }
  });

  it('the English does not promise a rebuilt sidebar to every profile', () => {
    const en = readFileSync(join(LOCALES, 'en.ts'), 'utf-8');
    // The claim a workspace makes is only true for the profiles that have one,
    // and not every profile does, so a sentence promising it to all of them
    // would be false for the rest.
    expect(Object.keys(PRESET_WORKSPACES).length).toBeGreaterThan(0);
    expect(en).not.toMatch(/tailors? (exactly )?which modules appear in the sidebar/);
    expect(en).not.toMatch(/left menu is rebuilt to the company profile/);
  });
});
