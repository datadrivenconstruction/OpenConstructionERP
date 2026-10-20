import { describe, expect, it, beforeAll } from 'vitest';
import i18next from 'i18next';
import { extractErrorMessageFromBody } from '@/shared/lib/api';
import { formatFileSize } from '@/shared/lib/formatters';
import { disciplineLabel } from '@/shared/lib/disciplineLabel';
import {
  converterDescription,
  converterName,
  converterPlatformMessage,
  converterVersionLabel,
} from './converterText';

beforeAll(async () => {
  await i18next.init({
    lng: 'en',
    resources: {
      en: {
        translation: {
          'converters.name_dwg': 'DWG Converter',
          'converters.desc_dwg': 'Reads {{range}}.',
          'api_errors.drawing_use_dwg_takeoff': '{{filename}} is a 2D drawing.',
          'bim.federation.disc_struct': 'Structure',
        },
      },
    },
  });
});

describe('converter display text comes from the API row', () => {
  it('interpolates the range the backend sent', () => {
    const t = i18next.t.bind(i18next);
    expect(converterDescription(t, { id: 'dwg', name: 'x', format_range: 'DWG R13-2018' })).toBe(
      'Reads DWG R13-2018.',
    );
    expect(converterName(t, { id: 'dwg', name: 'x' })).toBe('DWG Converter');
  });

  it('falls back to the API name for an unknown converter id', () => {
    const t = i18next.t.bind(i18next);
    expect(converterName(t, { id: 'zzz', name: 'Zzz converter' })).toBe('Zzz converter');
  });

  it('shows a version, never a sha', () => {
    expect(converterVersionLabel('0.6.8', '0.6.7')).toBe('v0.6.8');
    expect(converterVersionLabel(null, '0.3.1-preview')).toBe('v0.3.1-preview');
  });

  it('names the format in the platform refusal', () => {
    const t = i18next.t.bind(i18next);
    expect(converterPlatformMessage(t, 'rvt')).toContain('RVT');
    expect(converterPlatformMessage(t, 'rvt')).toContain('Windows');
  });
});

describe('coded backend refusals are shown in the UI language', () => {
  it('maps detail.code to the api_errors key and fills params', () => {
    const body = {
      detail: { code: 'drawing_use_dwg_takeoff', message: 'english', params: { filename: 'a.dwg' } },
    };
    expect(extractErrorMessageFromBody(body)).toBe('a.dwg is a 2D drawing.');
  });

  it('uses the English message for a code without a key', () => {
    const body = { detail: { code: 'never_heard_of_it', message: 'English fallback' } };
    expect(extractErrorMessageFromBody(body)).toBe('English fallback');
  });
});

describe('small display helpers', () => {
  it('shows a 40 KB file in KB, not 0 MB', () => {
    expect(formatFileSize(40 * 1024)).toMatch(/KB/);
  });

  it('translates a known discipline and leaves an unknown one alone', () => {
    const t = i18next.t.bind(i18next);
    expect(disciplineLabel(t, 'structural')).toBe('Structure');
    expect(disciplineLabel(t, 'weird')).toBe('weird');
  });
});
