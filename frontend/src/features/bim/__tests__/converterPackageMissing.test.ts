// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * An install that fails because the converter release no longer offers the
 * pinned asset is reported by code, so the sentence is translated and names
 * the asset and tag instead of echoing a raw English backend error.
 */
import { beforeAll, describe, expect, it } from 'vitest';
import i18next from 'i18next';

import { converterInstallMessage } from '../api';

beforeAll(async () => {
  if (!i18next.isInitialized) {
    await i18next.init({ lng: 'en', resources: {}, interpolation: { escapeValue: false } });
  }
});

describe('converterInstallMessage', () => {
  it('turns converter_package_missing into a sentence naming the asset and tag', () => {
    const text = converterInstallMessage({
      message: 'raw backend text',
      error_code: 'converter_package_missing',
      asset: 'DDC-RVT-Converter-0.6.8-portable.zip',
      tag: 'v2026.10.0',
    });
    expect(text).toContain('DDC-RVT-Converter-0.6.8-portable.zip');
    expect(text).toContain('v2026.10.0');
    expect(text).toContain('Update OpenConstructionERP');
    expect(text).not.toContain('raw backend text');
  });

  it('keeps the backend message for any other failure', () => {
    expect(converterInstallMessage({ message: 'Disk full' })).toBe('Disk full');
    expect(converterInstallMessage({ message: 'x', error_code: 'something_else' })).toBe('x');
  });
});
